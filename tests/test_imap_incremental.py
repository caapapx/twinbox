from __future__ import annotations

import json
from pathlib import Path

from twinbox_core import imap_incremental


class FakeIMAP:
    def __init__(self) -> None:
        self.selected: list[str] = []
        self.uid_calls: list[tuple[str, ...]] = []
        self.logged_in_as: tuple[str, str] | None = None
        self.logged_out = False
        self._selected_folder = ""
        self.uidvalidity = {"INBOX": "42", "Sent": "17"}
        self.search_results = {"INBOX": b"4 5", "Sent": b""}
        self.fetch_rows = {
            "4,5": [
                {
                    "uid": 4,
                    "envelope": {
                        "id": "4",
                        "subject": "Re: 项目北辰资源申请",
                        "date": "2026-03-26T10:00:00+08:00",
                    },
                    "flags": ["Seen"],
                },
                {
                    "uid": 5,
                    "envelope": {
                        "id": "5",
                        "subject": "新报价确认",
                        "date": "2026-03-26T10:05:00+08:00",
                    },
                    "flags": [],
                },
            ]
        }

    def login(self, login: str, password: str):
        self.logged_in_as = (login, password)
        return "OK", [b"logged in"]

    def select(self, folder: str, readonly: bool = True):
        self.selected.append(folder)
        self._selected_folder = folder
        return "OK", [f"1 [UIDVALIDITY {self.uidvalidity[folder]}]".encode()]

    def uid(self, command: str, *args: str):
        self.uid_calls.append((command, *args))
        if command == "SEARCH":
            return "OK", [self.search_results[self._selected_folder]]
        if command == "FETCH":
            return "OK", [json.dumps(self.fetch_rows.get(args[0], [])).encode()]
        raise AssertionError(f"unexpected uid command: {command}")

    def logout(self):
        self.logged_out = True
        return "BYE", [b"logout"]


class RealFetchIMAP(FakeIMAP):
    def __init__(self) -> None:
        super().__init__()
        self.fetch_rows = {}

    def uid(self, command: str, *args: str):
        self.uid_calls.append((command, *args))
        if command == "SEARCH":
            return "OK", [self.search_results[self._selected_folder]]
        if command == "FETCH":
            return (
                "OK",
                [
                    (
                        b'1 (UID 4 FLAGS (\\Seen))',
                        (
                            b"Subject: Re: \xe9\xa1\xb9\xe7\x9b\xae\xe5\x8c\x97\xe8\xbe\xb0\xe8\xb5\x84\xe6\xba\x90\xe7\x94\xb3\xe8\xaf\xb7\r\n"
                            b"From: Alice <alice@example.com>\r\n"
                            b"Date: Wed, 26 Mar 2026 10:00:00 +0800\r\n"
                            b"Message-Id: <msg-4@example.com>\r\n\r\n"
                        ),
                    ),
                    (
                        b'2 (UID 5 FLAGS ())',
                        (
                            b"Subject: \xe6\x96\xb0\xe6\x8a\xa5\xe4\xbb\xb7\xe7\xa1\xae\xe8\xae\xa4\r\n"
                            b"From: Bob <bob@example.com>\r\n"
                            b"Date: Wed, 26 Mar 2026 10:05:00 +0800\r\n"
                            b"Message-Id: <msg-5@example.com>\r\n\r\n"
                        ),
                    ),
                ],
            )
        raise AssertionError(f"unexpected uid command: {command}")


def test_load_watermarks_returns_empty_dict_for_missing_file(tmp_path):
    assert imap_incremental.load_uid_watermarks(tmp_path) == {}


def test_save_uid_watermarks_persists_json_payload(tmp_path):
    payload = {
        "INBOX": {
            "uidvalidity": 42,
            "last_uid": 123,
            "last_sync_at": "2026-03-26T10:00:00+08:00",
        }
    }

    path = imap_incremental.save_uid_watermarks(tmp_path, payload)

    assert path == tmp_path / "runtime" / "context" / "uid-watermarks.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == payload


def test_fetch_incremental_envelopes_fetches_only_uids_above_last_uid(tmp_path, monkeypatch):
    fake = FakeIMAP()
    monkeypatch.setattr(imap_incremental.imaplib, "IMAP4_SSL", lambda host, port: fake)

    result = imap_incremental.fetch_incremental_envelopes(
        state_root=tmp_path,
        folders=["INBOX"],
        imap_config={
            "host": "imap.example.com",
            "port": 993,
            "login": "user@example.com",
            "password": "secret",
        },
        watermarks={"INBOX": {"uidvalidity": 42, "last_uid": 3}},
    )

    assert ("SEARCH", None, "UID", "4:*") in fake.uid_calls
    assert result["uidvalidity_changed"] == []
    assert [row["uid"] for row in result["new_envelopes"]] == [4, 5]
    assert result["updated_watermarks"]["INBOX"]["last_uid"] == 5
    assert result["updated_watermarks"]["INBOX"]["uidvalidity"] == 42
    assert fake.logged_in_as == ("user@example.com", "secret")
    assert fake.logged_out is True


def test_fetch_incremental_envelopes_marks_folder_for_rescan_when_uidvalidity_changes(tmp_path, monkeypatch):
    fake = FakeIMAP()
    monkeypatch.setattr(imap_incremental.imaplib, "IMAP4_SSL", lambda host, port: fake)

    result = imap_incremental.fetch_incremental_envelopes(
        state_root=tmp_path,
        folders=["INBOX"],
        imap_config={
            "host": "imap.example.com",
            "port": 993,
            "login": "user@example.com",
            "password": "secret",
        },
        watermarks={"INBOX": {"uidvalidity": 99, "last_uid": 3}},
    )

    assert result["uidvalidity_changed"] == ["INBOX"]
    assert result["new_envelopes"] == []
    assert result["updated_watermarks"]["INBOX"]["uidvalidity"] == 42
    assert result["updated_watermarks"]["INBOX"]["last_uid"] == 0
    assert all(call[0] != "FETCH" for call in fake.uid_calls)


def test_fetch_incremental_envelopes_decodes_real_imap_fetch_tuples(tmp_path, monkeypatch):
    fake = RealFetchIMAP()
    monkeypatch.setattr(imap_incremental.imaplib, "IMAP4_SSL", lambda host, port: fake)

    result = imap_incremental.fetch_incremental_envelopes(
        state_root=tmp_path,
        folders=["INBOX"],
        imap_config={
            "host": "imap.example.com",
            "port": 993,
            "login": "user@example.com",
            "password": "secret",
        },
        watermarks={"INBOX": {"uidvalidity": 42, "last_uid": 3}},
    )

    assert result["folder_errors"] == []
    assert result["new_envelopes"][0]["id"] == "4"
    assert result["new_envelopes"][0]["from_addr"] == "alice@example.com"
    assert result["new_envelopes"][0]["flags"] == ["\\Seen"]
    assert result["new_envelopes"][1]["subject"] == "新报价确认"


def test_fetch_incremental_envelopes_reports_folder_errors_instead_of_skipping(tmp_path, monkeypatch):
    fake = FakeIMAP()
    fake.search_results["INBOX"] = b""

    def broken_select(folder: str, readonly: bool = True):
        return "NO", [b"permission denied"]

    fake.select = broken_select  # type: ignore[assignment]
    monkeypatch.setattr(imap_incremental.imaplib, "IMAP4_SSL", lambda host, port: fake)

    result = imap_incremental.fetch_incremental_envelopes(
        state_root=tmp_path,
        folders=["INBOX"],
        imap_config={
            "host": "imap.example.com",
            "port": 993,
            "login": "user@example.com",
            "password": "secret",
        },
        watermarks={"INBOX": {"uidvalidity": 42, "last_uid": 3}},
    )

    assert result["new_envelopes"] == []
    assert result["folder_errors"] == [
        {
            "folder": "INBOX",
            "step": "select",
            "detail": "permission denied",
        }
    ]


def test_run_incremental_phase1_returns_fallback_without_partial_writes_when_uidvalidity_changes(tmp_path):
    context_path = tmp_path / "runtime" / "context" / "phase1-context.json"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-25T09:00:00+08:00",
                "lookback_days": 7,
                "owner_domain": "example.com",
                "stats": {"folders_scanned": ["INBOX"], "total_envelopes": 1, "sampled_bodies": 1},
                "envelopes": [{"id": "100", "folder": "INBOX", "subject": "旧主题", "date": "2026-03-25T09:00:00+08:00"}],
                "sampled_bodies": {"100": {"subject": "旧主题", "body": "旧正文"}},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    watermark_path = tmp_path / "runtime" / "context" / "uid-watermarks.json"
    watermark_path.write_text(
        json.dumps({"INBOX": {"uidvalidity": 42, "last_uid": 100, "last_sync_at": "2026-03-25T09:00:00+08:00"}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = imap_incremental.run_incremental_phase1(
        state_root=tmp_path,
        folders=["INBOX"],
        imap_config={"host": "imap.example.com", "port": 993, "login": "user@example.com", "password": "secret"},
        account="myTwinbox",
        config_path=Path("/tmp/config.toml"),
        himalaya_bin="himalaya",
        sample_body_count=5,
        lookback_days=7,
        owner_email="user@example.com",
        fetcher=lambda **kwargs: {
            "new_envelopes": [],
            "updated_watermarks": {"INBOX": {"uidvalidity": 99, "last_uid": 0, "last_sync_at": "2026-03-26T10:00:00+08:00"}},
            "uidvalidity_changed": ["INBOX"],
            "folder_errors": [],
        },
    )

    assert result["status"] == "fallback_full"
    saved = json.loads(watermark_path.read_text(encoding="utf-8"))
    assert saved["INBOX"]["uidvalidity"] == 42
