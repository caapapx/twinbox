"""IMAP fetch transport tests (no live mailbox)."""

from __future__ import annotations

import unittest
from email.message import EmailMessage

from twinbox_core.imap_fetch import fetch_bodies_imap


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


if __name__ == "__main__":
    unittest.main()

class IncrementalImap(FakeImap):
    def __init__(self) -> None:
        super().__init__()
        self.login_count = 0
        self.logout_count = 0

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
            return "OK", [b"1"]
        uid_set = str(args[0]) if args else ""
        spec = str(args[-1] or "") if args else ""
        if command == "FETCH" and "HEADER.FIELDS" in spec:
            raw = b"Subject: sample\r\nFrom: sender@example.com\r\nDate: Tue, 1 Jan 2030 00:00:00 +0800\r\n\r\n"
            return "OK", [(b"1 (UID 1 FLAGS ())", raw)]
        return super().uid(command, uid_set, spec)


class TestIncrementalConnectionReuse(unittest.TestCase):
    def test_passes_envelope_connection_to_body_sampling(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest import mock

        from twinbox_core import imap_fetch

        client = IncrementalImap()
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(imap_fetch, "_build_client", return_value=client), \
             mock.patch.object(imap_fetch, "sample_bodies_imap", return_value={}) as sample, \
             mock.patch("twinbox_core.embeddings.embed_new_messages", return_value={"ok": True}):
            imap_fetch.fetch_incremental(
                Path(tmp), ["INBOX"], {"host": "h", "login": "u", "password": "p"}
            )

        self.assertEqual(client.login_count, 1)
        self.assertEqual(client.logout_count, 1)
        self.assertIs(sample.call_args.kwargs["client"], client)
