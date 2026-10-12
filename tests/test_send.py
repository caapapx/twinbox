"""Outbound send: SMTP/IMAP fully mocked; no network, no real credentials."""

from __future__ import annotations

import json
from email import message_from_bytes
from pathlib import Path
from unittest import mock

import pytest

from twinbox_core import send as outbound

HIMALAYA = '''
[accounts.t]
email = "me@example.com"
default = true
backend.type = "imap"
backend.host = "imap.example.com"
backend.port = 993
backend.login = "me@example.com"
backend.auth.type = "password"
backend.auth.raw = "imap-secret"
message.send.backend.type = "smtp"
message.send.backend.host = "smtp.example.com"
message.send.backend.port = 465
message.send.backend.encryption.type = "tls"
message.send.backend.login = "me@example.com"
message.send.backend.auth.type = "password"
message.send.backend.auth.cmd = "echo smtp-secret"
'''


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, *a, **k):
        self.sent = []
        self.logins = []
        FakeSMTP.instances.append(self)

    def login(self, user, pw):
        self.logins.append((user, pw))

    def sendmail(self, frm, rcpts, raw):
        self.sent.append((frm, list(rcpts), raw))
        return {}

    def quit(self):
        pass


class FakeIMAP:
    store: dict[str, list[bytes]] = {}
    appends: list[tuple] = []

    def __init__(self, *a, **k):
        self.folder = None

    def login(self, user, pw):
        assert pw == "imap-secret"

    def select(self, folder):
        self.folder = folder
        return "OK", [b"0"]

    def search(self, charset, *crit):
        mid = crit[-1].strip('"').encode()
        hits = [str(i + 1).encode() for i, raw in enumerate(FakeIMAP.store.get(self.folder, [])) if mid in raw]
        return "OK", [b" ".join(hits)]

    def append(self, folder, flags, date, raw):
        FakeIMAP.appends.append((folder, flags, date, raw))
        FakeIMAP.store.setdefault(folder, []).append(raw)
        return "OK", [b""]

    def logout(self):
        pass


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "himalaya.toml"
    cfg.write_text(HIMALAYA, encoding="utf-8")
    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.setenv("TWINBOX_HIMALAYA_CONFIG", str(cfg))
    monkeypatch.setenv("TWINBOX_SEND_ENABLED", "1")
    monkeypatch.delenv("TWINBOX_SEND_ALLOWED_DOMAINS", raising=False)
    FakeSMTP.instances.clear()
    FakeIMAP.store.clear()
    FakeIMAP.appends.clear()
    with mock.patch.object(outbound.smtplib, "SMTP_SSL", FakeSMTP), \
         mock.patch.object(outbound.imaplib, "IMAP4_SSL", FakeIMAP):
        yield tmp_path


def _draft(**kw):
    args = dict(to=["a@example.com"], cc=["c@example.com"], bcc=["b@example.com"],
                subject="周报(10.8-10.10)", plain="你好", html="<p>你好</p>")
    args.update(kw)
    res = outbound.create_draft(**args)
    assert res["ok"], res
    return res["data"]


def test_draft_writes_eml_and_never_sends(env):
    d = _draft()
    assert FakeSMTP.instances == []
    raw = Path(d["eml_path"]).read_bytes()
    msg = message_from_bytes(raw)
    assert msg["Message-ID"] == d["message_id"] and msg["Date"]
    assert msg["Bcc"] is None
    assert msg.is_multipart()
    assert "confirmation_token" in d and d["status"] == "draft"
    meta = json.loads(Path(d["eml_path"]).with_suffix(".json").read_text())
    assert d["confirmation_token"] not in json.dumps(meta)


def test_refuses_without_confirm(env):
    d = _draft()
    r = outbound.send_draft(d["draft_id"], confirm=False, confirmation_token=d["confirmation_token"])
    assert r == {"ok": False, "error": "confirmation_required"}
    assert FakeSMTP.instances == []


def test_refuses_bad_token_and_missing_draft(env):
    d = _draft()
    assert outbound.send_draft(d["draft_id"], confirm=True, confirmation_token="x")["error"] == "confirmation_token_invalid"
    assert outbound.send_draft("d" + "0" * 20, confirm=True, confirmation_token="x")["error"] == "draft_not_found"
    assert outbound.send_draft("../etc", confirm=True, confirmation_token="x")["error"] == "draft_not_found"
    assert FakeSMTP.instances == []


def test_refuses_when_disabled(env, monkeypatch):
    monkeypatch.setenv("TWINBOX_SEND_ENABLED", "0")
    d = _draft()
    r = outbound.send_draft(d["draft_id"], confirm=True, confirmation_token=d["confirmation_token"])
    assert r["error"] == "send_disabled" and FakeSMTP.instances == []


def test_domain_allowlist(env, monkeypatch):
    monkeypatch.setenv("TWINBOX_SEND_ALLOWED_DOMAINS", "example.com")
    r = outbound.create_draft(to=["x@evil.test"], subject="s", plain="b")
    assert r["error"] == "recipient_domain_not_allowed"


def test_send_appends_to_sent_items_and_marks_sent(env):
    d = _draft()
    r = outbound.send_draft(d["draft_id"], confirm=True, confirmation_token=d["confirmation_token"])
    assert r["ok"], r
    smtp = FakeSMTP.instances[0]
    assert smtp.logins == [("me@example.com", "smtp-secret")]
    frm, rcpts, raw = smtp.sent[0]
    assert sorted(rcpts) == ["a@example.com", "b@example.com", "c@example.com"]
    assert raw == Path(d["eml_path"]).read_bytes()
    folder, flags, _date, appended = FakeIMAP.appends[0]
    assert folder == '"Sent Items"' and flags == r"(\Seen)" and appended == raw
    data = r["data"]
    assert data["status"] == "sent" and data["sent_items_verified"] is True
    assert data["smtp_refused"] == [] and len(data["smtp_accepted"]) == 3
    assert "smtp-secret" not in json.dumps(r) and "imap-secret" not in json.dumps(r)


def test_double_send_refused(env):
    d = _draft()
    assert outbound.send_draft(d["draft_id"], confirm=True, confirmation_token=d["confirmation_token"])["ok"]
    again = outbound.send_draft(d["draft_id"], confirm=True, confirmation_token=d["confirmation_token"])
    assert again["error"] == "draft_already_sent"
    assert len(FakeSMTP.instances) == 1


def test_sent_items_dedup_by_message_id(env):
    d = _draft()
    raw = Path(d["eml_path"]).read_bytes()
    FakeIMAP.store['"Sent Items"'] = [raw]
    r = outbound.send_draft(d["draft_id"], confirm=True, confirmation_token=d["confirmation_token"])
    assert r["data"]["sent_items"]["already_present"] is True
    assert FakeIMAP.appends == [] and r["data"]["sent_items_verified"] is True


def test_cli_send_requires_confirm_flag(env, capsys):
    from twinbox_core import cli
    d = _draft()
    rc = cli.main(["send", "--json", "--draft-id", d["draft_id"], "--confirmation-token", d["confirmation_token"]])
    assert rc == 1 and json.loads(capsys.readouterr().out)["error"] == "confirmation_required"


def test_save_draft_appends_to_drafts_and_never_sends(env, monkeypatch):
    monkeypatch.delenv("TWINBOX_SEND_ENABLED", raising=False)
    d = _draft()
    r = outbound.save_draft_to_mailbox(d["draft_id"])
    assert r["ok"], r
    assert FakeSMTP.instances == []
    folder, flags, _date, raw = FakeIMAP.appends[0]
    assert folder == '"Drafts"' and flags == r"(\Draft)" and raw == Path(d["eml_path"]).read_bytes()
    assert r["data"]["drafts"]["verified"] is True
    again = outbound.save_draft_to_mailbox(d["draft_id"])
    assert again["data"]["drafts"]["already_present"] is True and len(FakeIMAP.appends) == 1
    assert outbound.save_draft_to_mailbox("nope")["error"] == "draft_not_found"
