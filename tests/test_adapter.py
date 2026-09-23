"""Ingest envelopes are reference-only and cursor-stable."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from twinbox_core.adapter import build_ingest_envelopes


class TestAdapter(unittest.TestCase):
    def test_no_body_fields_and_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pulse = root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
            pulse.parent.mkdir(parents=True, exist_ok=True)
            pulse.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-09-15T10:00:00+08:00",
                        "thread_index": [
                            {
                                "thread_key": "proj-alpha",
                                "latest_subject": "周报",
                                "last_activity_at": "2026-09-15T09:00:00+08:00",
                                "latest_message_ref": "1",
                                "why": "需要回复",
                                "recipient_role": "to",
                                "queue_tags": ["pending"],
                            },
                            {
                                "thread_key": "proj-beta",
                                "latest_subject": "风险",
                                "last_activity_at": "2026-09-15T09:30:00+08:00",
                                "latest_message_ref": "2",
                                "why": "关注",
                                "recipient_role": "cc",
                                "queue_tags": ["urgent"],
                            },
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            first = build_ingest_envelopes(root, account_id="default", limit=10)
            self.assertTrue(first["ok"])
            self.assertEqual(first["count"], 2)
            blob = json.dumps(first)
            for banned in ("body", "html", "attachment", "mime", "rfc822"):
                self.assertNotIn(f'"{banned}"', blob)
            for env in first["envelopes"]:
                self.assertEqual(env["source_account"], "default")
                self.assertIn("reference", env)
                self.assertLessEqual(len(env["metadata"]["excerpt"]), 280)

            nxt = first["cursor"]["next"]
            second = build_ingest_envelopes(root, account_id="default", since_cursor=nxt, limit=10)
            self.assertEqual(second["count"], 0)


if __name__ == "__main__":
    unittest.main()


def _write_pulse(root: Path, rows):
    pulse = root / "runtime/validation/phase-4/activity-pulse.json"
    pulse.parent.mkdir(parents=True, exist_ok=True)
    pulse.write_text(json.dumps({"generated_at": "2026-09-20T10:00:00+08:00", "thread_index": rows}), encoding="utf-8")


def test_versioned_cursor_freezes_high_watermark_during_concurrent_add(tmp_path):
    _write_pulse(tmp_path, [
        {"thread_key": "a", "latest_message_ref": "INBOX#1", "last_activity_at": "2026-09-20T08:00:00+08:00"},
        {"thread_key": "b", "latest_message_ref": "INBOX#2", "last_activity_at": "2026-09-20T09:00:00+08:00"},
    ])
    first = build_ingest_envelopes(tmp_path, account_id="acct-a", limit=1)
    assert first["cursor"]["next"].startswith("tbx1.")
    _write_pulse(tmp_path, [
        {"thread_key": "new", "latest_message_ref": "INBOX#3", "last_activity_at": "2026-09-20T10:00:00+08:00"},
        {"thread_key": "a", "latest_message_ref": "INBOX#1", "last_activity_at": "2026-09-20T08:00:00+08:00"},
        {"thread_key": "b", "latest_message_ref": "INBOX#2", "last_activity_at": "2026-09-20T09:00:00+08:00"},
    ])
    second = build_ingest_envelopes(tmp_path, account_id="acct-a", since_cursor=first["cursor"]["next"], limit=1)
    assert second["count"] == 1
    assert second["envelopes"][0]["reference"]["thread_key"] == "b"
    assert second["cursor"]["next"] is None
    restarted = build_ingest_envelopes(tmp_path, account_id="acct-a", limit=10)
    assert {e["reference"]["thread_key"] for e in restarted["envelopes"]} == {"new", "a", "b"}


def test_cursor_scope_and_version_are_checked(tmp_path):
    _write_pulse(tmp_path, [{"thread_key": "a", "latest_message_ref": "1"}, {"thread_key": "b", "latest_message_ref": "2"}])
    cursor = build_ingest_envelopes(tmp_path, account_id="acct-a", limit=1)["cursor"]["next"]
    mismatch = build_ingest_envelopes(tmp_path, account_id="acct-b", since_cursor=cursor, limit=1)
    assert mismatch["ok"] is False and mismatch["error"] == "cursor_scope_mismatch"
    unsupported = build_ingest_envelopes(tmp_path, account_id="acct-a", since_cursor="tbx2.aaaa", limit=1)
    assert unsupported["ok"] is False and unsupported["error"] == "unsupported_cursor_version"


def test_ingest_projects_case_semantics_without_body(tmp_path):
    from twinbox_core.classification_store import publish_classifications
    _write_pulse(tmp_path, [{"thread_key": "a", "latest_message_ref": "INBOX#1", "latest_subject": "Review"}])
    publish_classifications(
        tmp_path, scope_id="acct-a", cases=[{"case_key": "INBOX#1", "mail_refs": ["INBOX#1"]}],
        classifications=[{"case_key": "INBOX#1", "status": "classified", "primary_event_type": "approval", "tags": {"project": ["p1"]}}],
        coverage={"state": "complete"}, pack_fingerprint="p1", classifier_version="c1", source_revision=1,
    )
    result = build_ingest_envelopes(tmp_path, account_id="acct-a", limit=10)
    item = result["envelopes"][0]
    assert item["case_ref"].startswith("case_")
    assert item["semantics"]["primary_event_type"] == "approval"
    assert "body" not in json.dumps(item)


def test_fresh_cursor_snapshot_prunes_expired_cache_files(tmp_path):
    stale = tmp_path / "runtime/context/ingest-cursors/stale.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps({"scope": "acct-a", "expires_at": 0, "envelopes": []}), encoding="utf-8")
    _write_pulse(tmp_path, [{"thread_key": "a", "latest_message_ref": "1"}])

    result = build_ingest_envelopes(tmp_path, account_id="acct-a", limit=1)

    assert result["ok"] is True
    assert not stale.exists()
    assert len(list(stale.parent.glob("*.json"))) == 1
