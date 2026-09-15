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
