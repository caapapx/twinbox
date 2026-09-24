"""IMAP fetch transport tests (no live mailbox)."""

from __future__ import annotations

import unittest
from email.message import EmailMessage

from twinbox_core.imap_fetch import _decode_fetch_rows, fetch_bodies_imap


class FakeImap:
    def __init__(self) -> None:
        self.fetches: list[str] = []

    def select(self, _folder: str, readonly: bool = False):
        self.readonly = readonly
        return "OK", []

    def uid(self, command: str, uid_set: str, spec: str):
        self.fetches.append(uid_set)
        data = []
        for uid in uid_set.split(","):
            msg = EmailMessage()
            msg.set_content(f"body-{uid}")
            data.append((f"1 (UID {uid} BODY[] {{{len(msg.as_bytes())}}}".encode(), msg.as_bytes()))
        return "OK", data


def env(uid: str, folder: str = "INBOX") -> dict:
    return {"id": uid, "folder": folder, "subject": f"mail-{uid}"}


class TestBatchBodyFetch(unittest.TestCase):
    def test_fetches_one_folder_in_one_batch_and_decodes_each_uid(self) -> None:
        client = FakeImap()
        envelopes = [env("1"), env("2"), env("3")]
        bodies = fetch_bodies_imap(envelopes, {}, client=client)
        self.assertEqual(client.fetches, ["1,2,3"])
        self.assertEqual(bodies, {"INBOX#1": "body-1\n", "INBOX#2": "body-2\n", "INBOX#3": "body-3\n"})

    def test_chunks_large_folder_fetches(self) -> None:
        client = FakeImap()
        envelopes = [env(str(i)) for i in range(1, 22)]
        fetch_bodies_imap(envelopes, {}, client=client)
        self.assertEqual(client.fetches, [",".join(str(i) for i in range(1, 21)), "21"])


class TestHeaderDecodeTolerance(unittest.TestCase):
    def test_encoded_lf_in_from_does_not_abort_batch(self) -> None:
        """One defective From (encoded CR/LF) must not drop neighboring UIDs."""
        bad = (
            b"Subject: bad\r\n"
            b"From: =?utf-8?q?Alice=0ABob?= <evil@example.com>\r\n"
            b"Date: Tue, 1 Jan 2030 00:00:00 +0800\r\n\r\n"
        )
        good = (
            b"Subject: good\r\n"
            b"From: ok@example.com\r\n"
            b"Date: Tue, 1 Jan 2030 01:00:00 +0800\r\n\r\n"
        )
        rows = _decode_fetch_rows(
            [
                (b"1 (UID 11 FLAGS ())", bad),
                (b"2 (UID 12 FLAGS (\\Seen))", good),
            ],
            "INBOX",
        )
        self.assertEqual([r["id"] for r in rows], ["11", "12"])
        self.assertEqual(rows[1]["from_addr"], "ok@example.com")
        self.assertEqual(rows[1]["subject"], "good")
        self.assertEqual(rows[1]["flags"], ["Seen"])
        # Bad row kept with best-effort fields (compat32); must not raise.
        joined = f"{rows[0].get('from_addr','')}{rows[0].get('from_name','')}{rows[0].get('to','')}"
        self.assertTrue("evil@example.com" in joined or rows[0]["subject"] == "bad")


class TestFlagCanonicalize(unittest.TestCase):
    def test_backslash_seen_is_canonical(self) -> None:
        from twinbox_core.imap_fetch import canonicalize_flags, is_unread

        self.assertEqual(canonicalize_flags(["\\Seen", "\\Flagged"]), ["Seen", "Flagged"])
        self.assertFalse(is_unread(["\\Seen"]))
        self.assertTrue(is_unread([]))
        self.assertTrue(is_unread(["Flagged"]))

    def test_decode_flags_fetch(self) -> None:
        from twinbox_core.imap_fetch import _decode_flags_fetch

        got = _decode_flags_fetch(
            [
                b"1 (UID 10 FLAGS (\\Seen))",
                (b"2 (UID 11 FLAGS ())", b""),
            ]
        )
        self.assertEqual(got["10"], ["Seen"])
        self.assertEqual(got["11"], [])

    def test_default_policy_would_raise_but_helper_survives(self) -> None:
        from email.parser import BytesHeaderParser
        from email.policy import default as email_policy

        raw = b"From: =?utf-8?q?Alice=0ABob?= <evil@example.com>\r\nSubject: x\r\n\r\n"
        with self.assertRaises(ValueError):
            BytesHeaderParser(policy=email_policy).parsebytes(raw).get("from")
        rows = _decode_fetch_rows([(b"1 (UID 7 FLAGS ())", raw)], "INBOX")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "7")


class IncrementalImap(FakeImap):
    def __init__(self) -> None:
        super().__init__()
        self.login_count = 0
        self.logout_count = 0
        self.flag_fetches: list[str] = []
        self.flags_by_uid: dict[str, str] = {}

    def login(self, _user: str, _password: str):
        self.login_count += 1
        return "OK", []

    def logout(self):
        self.logout_count += 1
        return "BYE", []

    def select(self, _folder: str, readonly: bool = False):
        self.readonly = readonly
        return "OK", [b"[UIDVALIDITY 1]"]

    def uid(self, command: str, *args: str | None):
        if command == "SEARCH":
            return "OK", [b""]  # no new UIDs
        uid_set = str(args[0]) if args else ""
        spec = str(args[-1] or "") if args else ""
        if command == "FETCH" and "HEADER.FIELDS" in spec:
            raw = b"Subject: sample\r\nFrom: sender@example.com\r\nDate: Tue, 1 Jan 2030 00:00:00 +0800\r\n\r\n"
            return "OK", [(b"1 (UID 1 FLAGS ())", raw)]
        if command == "FETCH" and "FLAGS" in spec and "HEADER" not in spec:
            self.flag_fetches.append(uid_set)
            data = []
            for uid in uid_set.split(","):
                flags = self.flags_by_uid.get(uid, "\\Seen")
                data.append(f"1 (UID {uid} FLAGS ({flags}))".encode())
            return "OK", data
        return super().uid(command, uid_set, spec)


class TestIncrementalConnectionReuse(unittest.TestCase):
    def test_fetch_incremental_logs_in_once(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest import mock

        from twinbox_core import imap_fetch

        client = IncrementalImap()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(imap_fetch, "_build_client", return_value=client), \
                 mock.patch.object(imap_fetch, "sample_bodies_imap", return_value={}):
                result = imap_fetch.fetch_incremental(
                    root,
                    ["INBOX"],
                    {"host": "x", "login": "u", "password": "p", "port": 993, "encryption": "tls"},
                    sample_body_count=0,
                )
        self.assertIn(result.get("status"), {"ok", "noop"})
        self.assertEqual(client.login_count, 1)
        self.assertEqual(client.logout_count, 1)


class TestFlagsRefresh(unittest.TestCase):
    def test_lookback_flags_refresh_not_new_mail(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock

        from twinbox_core import imap_fetch

        client = IncrementalImap()
        client.flags_by_uid = {"42": "\\Seen"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = root / "runtime" / "context" / "phase1-context.json"
            ctx.parent.mkdir(parents=True, exist_ok=True)
            ctx.write_text(
                json.dumps(
                    {
                        "envelopes": [
                            {
                                "id": "42",
                                "folder": "INBOX",
                                "subject": "old unread",
                                "date": "2030-01-10T12:00:00+08:00",
                                "flags": [],
                                "from_addr": "a@example.com",
                            }
                        ],
                        "sampled_bodies": {},
                    }
                ),
                encoding="utf-8",
            )
            # watermark so SEARCH finds nothing new
            wm = root / "runtime" / "context" / "uid-watermarks.json"
            wm.write_text(
                json.dumps({"INBOX": {"uidvalidity": 1, "last_uid": 42, "last_sync_at": "x"}}),
                encoding="utf-8",
            )
            with mock.patch.object(imap_fetch, "_build_client", return_value=client), \
                 mock.patch.object(imap_fetch, "sample_bodies_imap", return_value={}), \
                 mock.patch("twinbox_core.config.owner_email", return_value="me@example.com"), \
                 mock.patch.object(imap_fetch, "embed_new_messages", create=True):
                # embed is imported inside fetch; patch embeddings module
                with mock.patch("twinbox_core.embeddings.embed_new_messages", return_value=None):
                    result = imap_fetch.fetch_incremental(
                        root,
                        ["INBOX"],
                        {"host": "x", "login": "u", "password": "p", "port": 993, "encryption": "tls"},
                        sample_body_count=0,
                        lookback_days=30,
                    )
            self.assertEqual(result.get("status"), "noop")
            self.assertEqual(result.get("new_envelope_ids"), [])
            self.assertEqual(result.get("new_envelope_count"), 0)
            self.assertGreaterEqual(int(result.get("flags_refreshed_count") or 0), 1)
            self.assertTrue(client.flag_fetches)
            merged = json.loads(
                (root / "runtime" / "validation" / "phase-1" / "raw" / "envelopes-merged.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(merged[0]["flags"], ["Seen"])


class ExpandLookbackImap(IncrementalImap):
    def uid(self, command: str, *args: str | None):
        joined = " ".join(str(a) for a in args if a is not None)
        if command == "SEARCH" and "SINCE" in joined:
            return "OK", [b"10"]
        if command == "SEARCH":
            return "OK", [b""]
        if command == "FETCH" and "HEADER.FIELDS" in joined:
            uid = str(args[0]).split(",")[0]
            raw = b"Subject: backfill\r\nFrom: sender@example.com\r\nDate: Tue, 1 Jan 2030 00:00:00 +0800\r\n\r\n"
            return "OK", [(f"1 (UID {uid} FLAGS ())".encode(), raw)]
        return super().uid(command, *args)


class UvResetImap(IncrementalImap):
    def select(self, _folder: str, readonly: bool = False):
        self.readonly = readonly
        return "OK", [b"[UIDVALIDITY 99]"]

    def uid(self, command: str, *args: str | None):
        joined = " ".join(str(a) for a in args if a is not None)
        if command == "SEARCH":
            if "SINCE" in joined:
                return "OK", [b""]
            return "OK", [b"5"]
        if command == "FETCH" and "HEADER.FIELDS" in joined:
            raw = b"Subject: rebuilt\r\nFrom: sender@example.com\r\nDate: Tue, 1 Jan 2030 00:00:00 +0800\r\n\r\n"
            return "OK", [(b"1 (UID 5 FLAGS ())", raw)]
        return super().uid(command, *args)


class TestLookbackAndUidvalidity(unittest.TestCase):
    def test_expand_lookback_backfills_trimmed_uid(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock

        from twinbox_core import imap_fetch

        client = ExpandLookbackImap()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = root / "runtime" / "context" / "phase1-context.json"
            ctx.parent.mkdir(parents=True, exist_ok=True)
            ctx.write_text(
                json.dumps({
                    "lookback_days": 7,
                    "envelopes": [{
                        "id": "42",
                        "folder": "INBOX",
                        "subject": "recent",
                        "date": "2030-01-10T12:00:00+08:00",
                        "flags": [],
                    }],
                }),
                encoding="utf-8",
            )
            wm = root / "runtime" / "context" / "uid-watermarks.json"
            wm.write_text(json.dumps({"INBOX": {"uidvalidity": 1, "last_uid": 42}}), encoding="utf-8")
            with mock.patch.object(imap_fetch, "_build_client", return_value=client), \
                 mock.patch.object(imap_fetch, "sample_bodies_imap", return_value={}), \
                 mock.patch("twinbox_core.embeddings.embed_new_messages", return_value=None):
                result = imap_fetch.fetch_incremental(
                    root, ["INBOX"],
                    {"host": "x", "login": "u", "password": "p", "port": 993, "encryption": "tls"},
                    sample_body_count=0,
                    lookback_days=30,
                )
            ids = {row["id"] for row in json.loads(
                (root / "runtime" / "validation" / "phase-1" / "raw" / "envelopes-merged.json").read_text()
            )}
            self.assertIn("10", ids)
            self.assertIn("42", ids)
            self.assertGreaterEqual(int(result.get("new_envelope_count") or 0), 1)

    def test_uidvalidity_change_refetches_instead_of_skipping(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock

        from twinbox_core import imap_fetch

        client = UvResetImap()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = root / "runtime" / "context" / "phase1-context.json"
            ctx.parent.mkdir(parents=True, exist_ok=True)
            ctx.write_text(
                json.dumps({
                    "envelopes": [{
                        "id": "1",
                        "folder": "INBOX",
                        "subject": "stale-uid",
                        "date": "2030-01-10T12:00:00+08:00",
                    }],
                }),
                encoding="utf-8",
            )
            wm = root / "runtime" / "context" / "uid-watermarks.json"
            wm.write_text(json.dumps({"INBOX": {"uidvalidity": 1, "last_uid": 9}}), encoding="utf-8")
            with mock.patch.object(imap_fetch, "_build_client", return_value=client), \
                 mock.patch.object(imap_fetch, "sample_bodies_imap", return_value={}), \
                 mock.patch("twinbox_core.embeddings.embed_new_messages", return_value=None) as embed:
                result = imap_fetch.fetch_incremental(
                    root, ["INBOX"],
                    {"host": "x", "login": "u", "password": "p", "port": 993, "encryption": "tls"},
                    sample_body_count=0,
                )
            merged = json.loads(
                (root / "runtime" / "validation" / "phase-1" / "raw" / "envelopes-merged.json").read_text()
            )
            ids = {row["id"] for row in merged}
            self.assertIn("5", ids)
            self.assertNotIn("1", ids)
            wm_after = json.loads(wm.read_text())
            self.assertEqual(int(wm_after["INBOX"]["uidvalidity"]), 99)
            self.assertEqual(result["uidvalidity_reset_folders"], ["INBOX"])
            # Rebuilt UIDs may repopulate the local window, but are not newly
            # arrived work and must never enqueue later LLM analysis.
            self.assertEqual(result["new_envelope_ids"], [])
            self.assertEqual(embed.call_args.kwargs.get("reset_folders"), {"INBOX"})


class _QueryImap:
    def __init__(self, folders: dict) -> None:
        self.folders = folders
        self.current = ""
        self.searches: list[tuple[str, tuple]] = []

    def login(self, _user: str, _password: str):
        return "OK", []

    def logout(self):
        return "BYE", []

    def select(self, folder: str, readonly: bool = True):
        self.current = folder
        spec = self.folders.get(folder, {"select": "NO"})
        return spec.get("select", "OK"), [b""]

    def uid(self, command: str, *args):
        spec = self.folders[self.current]
        if command == "SEARCH":
            self.searches.append((self.current, args))
            text = " ".join("" if part is None else str(part) for part in args)
            payload = spec.get("subject", b"") if "HEADER" in text else spec.get("date", b"")
            return spec.get("search_status", "OK"), [payload]
        uid_set = str(args[0])
        rows = []
        for uid in uid_set.split(","):
            raw = (
                f"Subject: weekly {uid}\r\nFrom: a@x\r\n"
                f"Date: Tue, 15 Jul 2025 10:00:00 +0800\r\n\r\n"
            ).encode()
            rows.append((f"1 (UID {uid} FLAGS ())".encode(), raw))
        return "OK", rows


class TestFetchByQuery(unittest.TestCase):
    def test_empty_subject_search_falls_back_to_date_window(self) -> None:
        from datetime import date
        from unittest import mock

        from twinbox_core import imap_fetch

        client = _QueryImap({"INBOX": {"select": "OK", "subject": b"", "date": b"10 11"}})
        with mock.patch.object(imap_fetch, "_build_client", return_value=client), \
             mock.patch("twinbox_core.config.owner_email", return_value=""), \
             mock.patch("twinbox_core.imap_fetch.fetch_bodies_imap", return_value={}):
            rows, errors = imap_fetch.fetch_by_query(
                {"host": "h", "login": "a", "password": "x"},
                ["INBOX"],
                since=date(2025, 7, 1),
                until=date(2025, 8, 1),
                fetch_bodies=False,
                subject_terms=["周报"],
            )
        self.assertEqual(errors, [])
        self.assertEqual(sorted(row["id"] for row in rows), ["10", "11"])
        kinds = ["subject" if "HEADER" in " ".join(str(p) for p in args) else "date" for _, args in client.searches]
        self.assertEqual(kinds, ["subject", "date"])

    def test_subject_hits_do_not_expand_window(self) -> None:
        from datetime import date
        from unittest import mock

        from twinbox_core import imap_fetch

        client = _QueryImap({"INBOX": {"select": "OK", "subject": b"7", "date": b"7 8 9"}})
        with mock.patch.object(imap_fetch, "_build_client", return_value=client), \
             mock.patch("twinbox_core.config.owner_email", return_value=""), \
             mock.patch("twinbox_core.imap_fetch.fetch_bodies_imap", return_value={}):
            rows, errors = imap_fetch.fetch_by_query(
                {"host": "h", "login": "a", "password": "x"},
                ["INBOX"],
                since=date(2025, 7, 1),
                until=date(2025, 8, 1),
                fetch_bodies=False,
                subject_terms=["weekly"],
            )
        self.assertEqual(errors, [])
        self.assertEqual([row["id"] for row in rows], ["7"])
        self.assertTrue(all("HEADER" in " ".join(str(p) for p in args) for _, args in client.searches))

    def test_partial_folder_failure_keeps_successful_folder(self) -> None:
        from datetime import date
        from unittest import mock

        from twinbox_core import imap_fetch

        client = _QueryImap({
            "Sent": {"select": "NO"},
            "INBOX": {"select": "OK", "date": b"3"},
        })
        with mock.patch.object(imap_fetch, "_build_client", return_value=client), \
             mock.patch("twinbox_core.config.owner_email", return_value=""), \
             mock.patch("twinbox_core.imap_fetch.fetch_bodies_imap", return_value={}):
            rows, errors = imap_fetch.fetch_by_query(
                {"host": "h", "login": "a", "password": "x"},
                ["Sent", "INBOX"],
                since=date(2025, 7, 1),
                fetch_bodies=False,
            )
        self.assertEqual([row["id"] for row in rows], ["3"])
        self.assertEqual(errors, [{"folder": "Sent", "step": "select", "detail": "SELECT failed"}])

