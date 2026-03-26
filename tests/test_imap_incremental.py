from __future__ import annotations

import json

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
