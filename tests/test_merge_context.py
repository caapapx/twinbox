from __future__ import annotations

import json

from twinbox_core import merge_context


def _write_context(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_merge_incremental_context_dedupes_by_id_and_folder_and_keeps_existing_bodies(tmp_path):
    existing_path = tmp_path / "runtime" / "context" / "phase1-context.json"
    _write_context(
        existing_path,
        {
            "generated_at": "2026-03-25T09:00:00+08:00",
            "lookback_days": 7,
            "owner_domain": "example.com",
            "envelopes": [
                {
                    "id": "100",
                    "folder": "INBOX",
                    "subject": "旧主题",
                    "date": "2026-03-25T09:00:00+08:00",
                    "flags": [],
                }
            ],
            "sampled_bodies": {
                "100": {
                    "subject": "旧主题",
                    "body": "旧正文",
                }
            },
            "stats": {
                "folders_scanned": ["INBOX"],
                "total_envelopes": 1,
                "sampled_bodies": 1,
            },
        },
    )

    merged = merge_context.merge_incremental_context(
        existing_path=existing_path,
        new_envelopes=[
            {
                "id": "100",
                "folder": "INBOX",
                "subject": "旧主题（已读）",
                "date": "2026-03-25T09:00:00+08:00",
                "flags": ["Seen"],
            },
            {
                "id": "101",
                "folder": "Sent",
                "subject": "新主题",
                "date": "2026-03-26T10:00:00+08:00",
                "flags": [],
            },
        ],
        new_bodies={
            "101": {
                "subject": "新主题",
                "body": "新正文",
            }
        },
    )

    assert [row["id"] for row in merged["envelopes"]] == ["100", "101"]
    assert merged["envelopes"][0]["flags"] == ["Seen"]
    assert merged["sampled_bodies"]["100"]["body"] == "旧正文"
    assert merged["sampled_bodies"]["101"]["body"] == "新正文"
    assert merged["stats"]["total_envelopes"] == 2
    assert merged["stats"]["sampled_bodies"] == 2
    assert merged["generated_at"]


def test_merge_incremental_context_trims_rows_older_than_lookback_window(tmp_path):
    existing_path = tmp_path / "runtime" / "context" / "phase1-context.json"
    _write_context(
        existing_path,
        {
            "generated_at": "2026-03-25T09:00:00+08:00",
            "lookback_days": 1,
            "envelopes": [
                {
                    "id": "old-1",
                    "folder": "INBOX",
                    "subject": "过期主题",
                    "date": "2026-01-01T09:00:00+08:00",
                    "flags": [],
                }
            ],
            "sampled_bodies": {
                "old-1": {
                    "subject": "过期主题",
                    "body": "旧正文",
                }
            },
            "stats": {},
        },
    )

    merged = merge_context.merge_incremental_context(
        existing_path=existing_path,
        new_envelopes=[
            {
                "id": "fresh-1",
                "folder": "INBOX",
                "subject": "最新主题",
                "date": "2026-03-26T10:00:00+08:00",
                "flags": [],
            }
        ],
        new_bodies={
            "fresh-1": {
                "subject": "最新主题",
                "body": "最新正文",
            }
        },
        now="2026-03-26T12:00:00+08:00",
    )

    assert [row["id"] for row in merged["envelopes"]] == ["fresh-1"]
    assert "old-1" not in merged["sampled_bodies"]
    assert merged["stats"]["total_envelopes"] == 1


def test_normalize_imap_envelope_returns_himalaya_compatible_shape():
    normalized = merge_context.normalize_imap_envelope(
        {
            "id": "200",
            "subject": "报价确认",
            "date": "2026-03-26T10:00:00+08:00",
            "from_name": "Alice",
            "from_addr": "alice@example.com",
            "flags": ["Seen"],
        },
        folder="INBOX",
    )

    assert normalized == {
        "id": "200",
        "folder": "INBOX",
        "subject": "报价确认",
        "date": "2026-03-26T10:00:00+08:00",
        "from": {"name": "Alice", "addr": "alice@example.com"},
        "has_attachment": False,
        "flags": ["Seen"],
    }
