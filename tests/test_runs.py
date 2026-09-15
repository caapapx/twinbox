"""Run history, error classes, and freshness."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from twinbox_core import runs


class TestRuns(unittest.TestCase):
    def test_append_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = runs.append_run(
                root,
                {
                    "run_id": "abc123",
                    "account_id": "default",
                    "job": "daytime-sync",
                    "ok": True,
                    "timings_ms": {"fetch_ms": 10},
                },
            )
            self.assertEqual(row["run_id"], "abc123")
            self.assertTrue(row["ok"])
            self.assertIsNotNone(row["success_at"])
            recent = runs.load_recent_runs(root, limit=5)
            self.assertEqual(len(recent), 1)
            freshness = runs.account_freshness(root)
            self.assertEqual(freshness["last_run_id"], "abc123")
            self.assertEqual(freshness["last_success_at"], row["success_at"])

    def test_history_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(60):
                runs.append_run(root, {"account_id": "default", "job": "quick-refresh", "ok": True}, keep=50)
            self.assertEqual(len(runs.load_recent_runs(root, limit=100)), 50)

    def test_classify_and_sanitize(self) -> None:
        self.assertEqual(
            runs.classify_error(step="fetch", message="IMAP login failed"),
            "imap_connect",
        )
        self.assertEqual(
            runs.classify_error(step="analysis", message="json parse error"),
            "analysis_parse",
        )
        cleaned = runs.sanitize_error_message("Authorization: Bearer SECRETTOKEN boom")
        self.assertNotIn("SECRETTOKEN", cleaned)
        self.assertIn("[redacted]", cleaned)


if __name__ == "__main__":
    unittest.main()
