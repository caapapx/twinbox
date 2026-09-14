"""cmd_sync quick-refresh skips LLM analysis; daytime-sync still runs it."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from twinbox_core import cli


def _fake_pulse(root: Path):
    out = root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    return {"generated_at": "2026-09-10T18:26:35+08:00", "summary": {"tracked_threads": 1}}, out


class TestQuickRefresh(unittest.TestCase):
    def _run(self, job: str) -> tuple[dict, mock.Mock]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            urgent = root / "runtime" / "validation" / "phase-4" / "daily-urgent.yaml"
            urgent.parent.mkdir(parents=True, exist_ok=True)
            urgent.write_text("generated_at: '2026-09-10T08:31:00+08:00'\ndaily_urgent: []\n", encoding="utf-8")
            run_analysis = mock.Mock(return_value={"ok": True})
            with mock.patch.object(cli, "_state_root", return_value=root), \
                 mock.patch("twinbox_core.config.resolve_imap_config", return_value={"host": "h", "login": "u"}), \
                 mock.patch("twinbox_core.imap_fetch.fetch_incremental", return_value={"status": "ok", "generated_at": "now"}) as fetch, \
                 mock.patch("twinbox_core.analyze.run_analysis", run_analysis), \
                 mock.patch("twinbox_core.pulse.write_activity_pulse", side_effect=lambda r: _fake_pulse(r)):
                result = cli.cmd_sync(job)
            self.assertEqual(fetch.call_args.kwargs["lookback_days"], 30 if job == "nightly-full" else 7)
            return result, run_analysis

    def test_quick_refresh_skips_analysis(self) -> None:
        result, run_analysis = self._run("quick-refresh")
        self.assertTrue(result["ok"])
        run_analysis.assert_not_called()
        self.assertTrue(result["analysis"]["skipped"])
        self.assertEqual(result["degraded"], [])
        self.assertTrue(result["consistency"]["analysis_skipped"])
        self.assertEqual(result["consistency"]["analysis_generated_at"], "2026-09-10T08:31:00+08:00")

    def test_daytime_sync_runs_analysis(self) -> None:
        result, run_analysis = self._run("daytime-sync")
        run_analysis.assert_called_once()
        self.assertFalse(result["consistency"]["analysis_skipped"])

    def test_nightly_lookback(self) -> None:
        self._run("nightly-full")


if __name__ == "__main__":
    unittest.main()
