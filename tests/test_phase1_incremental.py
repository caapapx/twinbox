from __future__ import annotations

import json
from pathlib import Path

from twinbox_core import imap_incremental


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_run_incremental_phase1_writes_context_raw_artifacts_and_watermarks(tmp_path):
    _write_json(
        tmp_path / "runtime" / "context" / "phase1-context.json",
        {
            "generated_at": "2026-03-25T09:00:00+08:00",
            "lookback_days": 7,
            "owner_domain": "example.com",
            "stats": {"folders_scanned": ["INBOX"], "total_envelopes": 1, "sampled_bodies": 1},
            "envelopes": [
                {"id": "100", "folder": "INBOX", "subject": "旧主题", "date": "2026-03-25T09:00:00+08:00", "flags": []}
            ],
            "sampled_bodies": {"100": {"subject": "旧主题", "body": "旧正文"}},
        },
    )
    _write_json(
        tmp_path / "runtime" / "context" / "uid-watermarks.json",
        {"INBOX": {"uidvalidity": 42, "last_uid": 100, "last_sync_at": "2026-03-25T09:00:00+08:00"}},
    )
    _write_json(
        tmp_path / "runtime" / "validation" / "phase-1" / "raw" / "sample-bodies.json",
        [{"id": "100", "folder": "INBOX", "subject": "旧主题", "body": "旧正文"}],
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
            "new_envelopes": [
                {
                    "id": "101",
                    "folder": "INBOX",
                    "subject": "新主题",
                    "date": "2026-03-26T10:00:00+08:00",
                    "flags": [],
                    "from_name": "Alice",
                    "from_addr": "alice@example.com",
                }
            ],
            "updated_watermarks": {"INBOX": {"uidvalidity": 42, "last_uid": 101, "last_sync_at": "2026-03-26T10:00:00+08:00"}},
            "uidvalidity_changed": [],
            "folder_errors": [],
        },
        body_sampler=lambda envelopes, **kwargs: {
            "101": {"subject": "新主题", "body": "新正文"}
        },
        now="2026-03-26T10:00:00+08:00",
    )

    context = json.loads((tmp_path / "runtime" / "context" / "phase1-context.json").read_text(encoding="utf-8"))
    raw_envelopes = json.loads((tmp_path / "runtime" / "validation" / "phase-1" / "raw" / "envelopes-merged.json").read_text(encoding="utf-8"))
    raw_bodies = json.loads((tmp_path / "runtime" / "validation" / "phase-1" / "raw" / "sample-bodies.json").read_text(encoding="utf-8"))
    watermarks = json.loads((tmp_path / "runtime" / "context" / "uid-watermarks.json").read_text(encoding="utf-8"))

    assert result["status"] == "incremental"
    assert [row["id"] for row in context["envelopes"]] == ["101", "100"]
    assert [row["id"] for row in raw_envelopes] == ["101", "100"]
    assert {row["id"] for row in raw_bodies} == {"100", "101"}
    assert context["sampled_bodies"]["101"]["body"] == "新正文"
    assert watermarks["INBOX"]["last_uid"] == 101


def test_run_incremental_phase1_noop_keeps_existing_context_when_no_new_mail(tmp_path):
    _write_json(
        tmp_path / "runtime" / "context" / "phase1-context.json",
        {
            "generated_at": "2026-03-25T09:00:00+08:00",
            "lookback_days": 7,
            "owner_domain": "example.com",
            "stats": {"folders_scanned": ["INBOX"], "total_envelopes": 1, "sampled_bodies": 1},
            "envelopes": [
                {"id": "100", "folder": "INBOX", "subject": "旧主题", "date": "2026-03-25T09:00:00+08:00", "flags": []}
            ],
            "sampled_bodies": {"100": {"subject": "旧主题", "body": "旧正文"}},
        },
    )
    _write_json(
        tmp_path / "runtime" / "context" / "uid-watermarks.json",
        {"INBOX": {"uidvalidity": 42, "last_uid": 100, "last_sync_at": "2026-03-25T09:00:00+08:00"}},
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
            "updated_watermarks": {"INBOX": {"uidvalidity": 42, "last_uid": 100, "last_sync_at": "2026-03-26T10:00:00+08:00"}},
            "uidvalidity_changed": [],
            "folder_errors": [],
        },
        body_sampler=lambda envelopes, **kwargs: {},
        now="2026-03-26T10:00:00+08:00",
    )

    context = json.loads((tmp_path / "runtime" / "context" / "phase1-context.json").read_text(encoding="utf-8"))
    watermarks = json.loads((tmp_path / "runtime" / "context" / "uid-watermarks.json").read_text(encoding="utf-8"))

    assert result["status"] == "noop"
    assert [row["id"] for row in context["envelopes"]] == ["100"]
    assert context["sampled_bodies"]["100"]["body"] == "旧正文"
    assert watermarks["INBOX"]["last_sync_at"] == "2026-03-26T10:00:00+08:00"
