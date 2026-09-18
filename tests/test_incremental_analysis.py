"""Incremental daytime analysis: skip on noop, merge YAML on new mail."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from twinbox_core.analyze import run_analysis


class TestIncrementalAnalysis(unittest.TestCase):
    def test_patch_keeps_other_thread_urgent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase4 = root / "runtime" / "validation" / "phase-4"
            ctx = root / "runtime" / "context" / "phase1-context.json"
            phase4.mkdir(parents=True)
            ctx.parent.mkdir(parents=True)
            ctx.write_text(
                json.dumps({
                    "lookback_days": 7,
                    "envelopes": [
                        {
                            "subject": "旧紧急",
                            "id": "1",
                            "folder": "INBOX",
                            "date": "2026-09-01T00:00:00+08:00",
                        },
                        {
                            "subject": "新邮件",
                            "id": "2",
                            "folder": "INBOX",
                            "date": "2026-09-16T00:00:00+08:00",
                        },
                    ],
                }),
                encoding="utf-8",
            )
            (phase4 / "daily-urgent.yaml").write_text(
                "generated_at: '2026-09-15T00:00:00+08:00'\n"
                "daily_urgent:\n"
                "  - thread_key: 旧紧急\n"
                "    why: 仍在\n",
                encoding="utf-8",
            )
            (phase4 / "weekly-brief-raw.json").write_text(
                json.dumps({"generated_at": "old", "summary": "keep"}),
                encoding="utf-8",
            )
            llm_json = (
                '{"daily_urgent": [{"thread_key": "新邮件", "why": "新"}], '
                '"pending_replies": [], "sla_risks": [], "weekly_brief": {"summary": "overwrite?"}}'
            )
            with mock.patch("twinbox_core.analyze.call_llm", return_value=llm_json), \
                    mock.patch("twinbox_core.select.choose_candidates", side_effect=lambda ctx, *_a, **_k: (
                        [e for e in ctx["envelopes"] if e["id"] == "2"],
                        {"embeddings_degraded": False},
                    )):
                result = run_analysis(root, only_ids={("INBOX", "2")})
            self.assertTrue(result["ok"])
            import yaml
            urgent = yaml.safe_load((phase4 / "daily-urgent.yaml").read_text())
            keys = {row.get("thread_key") for row in urgent["daily_urgent"]}
            self.assertEqual(keys, {"旧紧急", "新邮件"})
            weekly = json.loads((phase4 / "weekly-brief-raw.json").read_text())
            self.assertEqual(weekly["summary"], "keep")
            self.assertEqual(result["analyzed_ids"], [["INBOX", "2"]])
            self.assertNotIn("无关", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
