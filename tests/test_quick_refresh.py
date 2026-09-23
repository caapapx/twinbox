"""cmd_sync analysis paths: skip / incremental / full (mock IMAP + LLM)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from twinbox_core import cli


def _fake_pulse(root: Path):
    out = root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    return {"generated_at": "2026-09-10T18:26:35+08:00", "summary": {"tracked_threads": 1}}, out


def _write_urgent(root: Path) -> None:
    urgent = root / "runtime" / "validation" / "phase-4" / "daily-urgent.yaml"
    urgent.parent.mkdir(parents=True, exist_ok=True)
    urgent.write_text(
        "generated_at: '2026-09-10T08:31:00+08:00'\ndaily_urgent: []\n",
        encoding="utf-8",
    )


class TestQuickRefresh(unittest.TestCase):
    def _run(self, job: str) -> tuple[dict, mock.Mock]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_urgent(root)
            run_analysis = mock.Mock(return_value={"ok": True})
            with mock.patch.object(cli, "_account_root", return_value=root), \
                 mock.patch("twinbox_core.config.resolve_imap_config", return_value={"host": "h", "login": "u"}), \
                 mock.patch("twinbox_core.config.default_account_id", return_value="default"), \
                 mock.patch("twinbox_core.runs.append_run", return_value={}), \
                 mock.patch(
                     "twinbox_core.imap_fetch.fetch_incremental",
                     return_value={"status": "ok", "generated_at": "now"},
                 ) as fetch, \
                 mock.patch("twinbox_core.analyze.run_analysis", run_analysis), \
                 mock.patch("twinbox_core.pulse.write_activity_pulse", side_effect=lambda r, **_k: _fake_pulse(r)):
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
        self.assertEqual(result["analysis_path"], "quick")
        self.assertEqual(result["consistency"]["analysis_generated_at"], "2026-09-10T08:31:00+08:00")
        self.assertIn("run_id", result)

    def test_daytime_sync_runs_analysis(self) -> None:
        result, run_analysis = self._run("daytime-sync")
        run_analysis.assert_called_once()
        self.assertFalse(result["consistency"]["analysis_skipped"])
        self.assertEqual(result["analysis_path"], "full")
        self.assertIsNone(run_analysis.call_args.kwargs.get("only_ids"))

    def test_daytime_noop_skips_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_urgent(root)
            run_analysis = mock.Mock(return_value={"ok": True})
            with mock.patch.object(cli, "_account_root", return_value=root), \
                 mock.patch("twinbox_core.config.resolve_imap_config", return_value={"host": "h", "login": "u"}), \
                 mock.patch("twinbox_core.config.default_account_id", return_value="default"), \
                 mock.patch("twinbox_core.runs.append_run", return_value={}), \
                 mock.patch(
                     "twinbox_core.imap_fetch.fetch_incremental",
                     return_value={"status": "noop", "generated_at": "now", "new_envelope_count": 0},
                 ), \
                 mock.patch("twinbox_core.analyze.run_analysis", run_analysis), \
                 mock.patch("twinbox_core.pulse.write_activity_pulse", side_effect=lambda r, **_k: _fake_pulse(r)):
                result = cli.cmd_sync("daytime-sync")
            run_analysis.assert_not_called()
            self.assertTrue(result["analysis"]["skipped"])
            self.assertEqual(result["analysis"]["reason"], "no-new-mail")
            self.assertTrue(result["consistency"]["analysis_skipped"])
            self.assertEqual(result["analysis_path"], "skip")

    def test_daytime_new_mail_is_incremental(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_urgent(root)
            ctx = root / "runtime" / "context" / "phase1-context.json"
            ctx.parent.mkdir(parents=True, exist_ok=True)
            ctx.write_text(
                json.dumps({"envelopes": [{"id": "1", "folder": "INBOX"}]}),
                encoding="utf-8",
            )

            def fake_fetch(state_root, *_a, **_k):
                path = Path(state_root) / "runtime" / "context" / "phase1-context.json"
                path.write_text(
                    json.dumps({
                        "envelopes": [
                            {"id": "1", "folder": "INBOX"},
                            {"id": "2", "folder": "INBOX"},
                        ],
                    }),
                    encoding="utf-8",
                )
                return {
                    "status": "ok",
                    "generated_at": "now",
                    "new_envelope_count": 1,
                    "new_envelope_ids": [["INBOX", "2"]],
                }

            run_analysis = mock.Mock(return_value={"ok": True, "select": {"envelope_in": 2, "envelope_llm": 1}})
            with mock.patch.object(cli, "_account_root", return_value=root), \
                 mock.patch("twinbox_core.config.resolve_imap_config", return_value={"host": "h", "login": "u"}), \
                 mock.patch("twinbox_core.config.default_account_id", return_value="default"), \
                 mock.patch("twinbox_core.runs.append_run", return_value={}), \
                 mock.patch("twinbox_core.imap_fetch.fetch_incremental", side_effect=fake_fetch), \
                 mock.patch("twinbox_core.analyze.run_analysis", run_analysis), \
                 mock.patch("twinbox_core.pulse.write_activity_pulse", side_effect=lambda r, **_k: _fake_pulse(r)):
                result = cli.cmd_sync("daytime-sync")
            run_analysis.assert_called_once()
            self.assertEqual(run_analysis.call_args.kwargs.get("only_ids"), {("INBOX", "2")})
            self.assertEqual(result["analysis_path"], "incremental")
            self.assertFalse(result["consistency"]["analysis_skipped"])

    def test_daytime_duplicate_uid_does_not_full(self) -> None:
        """R8: IMAP new_envelope_count>0 but id already in window → skip, never full."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_urgent(root)
            ctx = root / "runtime" / "context" / "phase1-context.json"
            ctx.parent.mkdir(parents=True, exist_ok=True)
            ctx.write_text(
                json.dumps({"envelopes": [{"id": "9", "folder": "INBOX"}]}),
                encoding="utf-8",
            )

            def fake_fetch(state_root, *_a, **_k):
                # Same id still in context (duplicate / watermark re-fetch).
                path = Path(state_root) / "runtime" / "context" / "phase1-context.json"
                path.write_text(
                    json.dumps({"envelopes": [{"id": "9", "folder": "INBOX"}]}),
                    encoding="utf-8",
                )
                return {
                    "status": "ok",
                    "generated_at": "now",
                    "new_envelope_count": 1,
                    "new_envelope_ids": [["INBOX", "9"]],
                }

            run_analysis = mock.Mock(return_value={"ok": True})
            with mock.patch.object(cli, "_account_root", return_value=root), \
                 mock.patch("twinbox_core.config.resolve_imap_config", return_value={"host": "h", "login": "u"}), \
                 mock.patch("twinbox_core.config.default_account_id", return_value="default"), \
                 mock.patch("twinbox_core.runs.append_run", return_value={}), \
                 mock.patch("twinbox_core.imap_fetch.fetch_incremental", side_effect=fake_fetch), \
                 mock.patch("twinbox_core.analyze.run_analysis", run_analysis), \
                 mock.patch("twinbox_core.pulse.write_activity_pulse", side_effect=lambda r, **_k: _fake_pulse(r)):
                result = cli.cmd_sync("daytime-sync")
            run_analysis.assert_not_called()
            self.assertEqual(result["analysis_path"], "skip")
            self.assertEqual(result["analysis"]["reason"], "no-new-ids-in-window")

    def test_nightly_lookback(self) -> None:
        result, run_analysis = self._run("nightly-full")
        self.assertEqual(result["analysis_path"], "full")
        self.assertIsNone(run_analysis.call_args.kwargs.get("only_ids"))

    def test_daytime_missing_analysis_artifact_falls_back_to_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_ctx(root, [{"id": "1", "folder": "INBOX"}])
            run_analysis = mock.Mock(return_value={"ok": True, "analyzed_ids": [["INBOX", "1"]]})
            with mock.patch.object(cli, "_account_root", return_value=root), \
                 mock.patch("twinbox_core.config.resolve_imap_config", return_value={"host": "h", "login": "u"}), \
                 mock.patch("twinbox_core.config.default_account_id", return_value="default"), \
                 mock.patch("twinbox_core.runs.append_run", return_value={}), \
                 mock.patch(
                     "twinbox_core.imap_fetch.fetch_incremental",
                     return_value={"status": "noop", "generated_at": "now", "new_envelope_count": 0},
                 ), \
                 mock.patch("twinbox_core.analyze.run_analysis", run_analysis), \
                 mock.patch("twinbox_core.pulse.write_activity_pulse", side_effect=lambda r, **_k: _fake_pulse(r)):
                result = cli.cmd_sync("daytime-sync")
            run_analysis.assert_called_once()
            self.assertIsNone(run_analysis.call_args.kwargs.get("only_ids"))
            self.assertEqual(result["analysis_path"], "full")


def _write_ctx(root: Path, envelopes: list[dict]) -> None:
    path = root / "runtime" / "context" / "phase1-context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"envelopes": envelopes}), encoding="utf-8")


def _write_watermarks(root: Path, uidvalidity: int) -> None:
    path = root / "runtime" / "context" / "uid-watermarks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"INBOX": {"uidvalidity": uidvalidity, "last_uid": 9}}),
        encoding="utf-8",
    )


def _pending_ids(root: Path) -> set[tuple[str, str]]:
    ids, _uv = cli._load_pending(root)
    return ids


class TestPendingAnalysis(unittest.TestCase):
    def _sync(self, root: Path, job: str, fetch, analysis: mock.Mock | None = None):
        run_analysis = analysis or mock.Mock(return_value={"ok": True, "analyzed_ids": []})
        with mock.patch.object(cli, "_account_root", return_value=root), \
             mock.patch("twinbox_core.config.resolve_imap_config", return_value={"host": "h", "login": "u"}), \
             mock.patch("twinbox_core.config.default_account_id", return_value="default"), \
             mock.patch("twinbox_core.runs.append_run", return_value={}), \
             mock.patch("twinbox_core.imap_fetch.fetch_incremental", side_effect=fetch if callable(fetch) else None,
                        return_value=None if callable(fetch) else fetch), \
             mock.patch("twinbox_core.analyze.run_analysis", run_analysis), \
             mock.patch("twinbox_core.pulse.write_activity_pulse", side_effect=lambda r, **_k: _fake_pulse(r)):
            result = cli.cmd_sync(job)
        return result, run_analysis

    def test_quick_then_daytime_noop_still_analyzes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_urgent(root)
            _write_ctx(root, [{"id": "1", "folder": "INBOX"}])

            def quick_fetch(state_root, *_a, **_k):
                _write_ctx(Path(state_root), [
                    {"id": "1", "folder": "INBOX"},
                    {"id": "2", "folder": "INBOX"},
                ])
                return {
                    "status": "ok",
                    "generated_at": "now",
                    "new_envelope_count": 1,
                    "new_envelope_ids": [["INBOX", "2"]],
                }

            quick, _ = self._sync(root, "quick-refresh", quick_fetch)
            self.assertEqual(quick["analysis_path"], "quick")
            self.assertEqual(_pending_ids(root), {("INBOX", "2")})

            daytime, analysis = self._sync(
                root,
                "daytime-sync",
                {"status": "noop", "generated_at": "now", "new_envelope_count": 0, "new_envelope_ids": []},
                mock.Mock(return_value={"ok": True, "analyzed_ids": [["INBOX", "2"]]}),
            )
            analysis.assert_called_once()
            self.assertEqual(analysis.call_args.kwargs.get("only_ids"), {("INBOX", "2")})
            self.assertEqual(daytime["analysis_path"], "incremental")
            self.assertEqual(_pending_ids(root), set())

    def test_multiple_quick_enqueues_union(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_urgent(root)
            _write_ctx(root, [{"id": "1", "folder": "INBOX"}])

            def fetch_uid(uid: str):
                def _fetch(state_root, *_a, **_k):
                    current = json.loads(
                        (Path(state_root) / "runtime" / "context" / "phase1-context.json").read_text()
                    )
                    envelopes = list(current["envelopes"])
                    envelopes.append({"id": uid, "folder": "INBOX"})
                    _write_ctx(Path(state_root), envelopes)
                    return {
                        "status": "ok",
                        "generated_at": "now",
                        "new_envelope_count": 1,
                        "new_envelope_ids": [["INBOX", uid]],
                    }
                return _fetch

            self._sync(root, "quick-refresh", fetch_uid("2"))
            self._sync(root, "quick-refresh", fetch_uid("3"))
            self.assertEqual(_pending_ids(root), {("INBOX", "2"), ("INBOX", "3")})

    def test_duplicate_uid_does_not_enqueue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_urgent(root)
            _write_ctx(root, [{"id": "9", "folder": "INBOX"}])
            result, analysis = self._sync(
                root,
                "daytime-sync",
                {
                    "status": "ok",
                    "generated_at": "now",
                    "new_envelope_count": 1,
                    "new_envelope_ids": [["INBOX", "9"]],
                },
            )
            analysis.assert_not_called()
            self.assertEqual(result["analysis_path"], "skip")
            self.assertEqual(_pending_ids(root), set())

    def test_flags_only_does_not_enqueue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_urgent(root)
            _write_ctx(root, [{"id": "1", "folder": "INBOX"}])
            result, analysis = self._sync(
                root,
                "quick-refresh",
                {
                    "status": "ok",
                    "generated_at": "now",
                    "new_envelope_count": 0,
                    "new_envelope_ids": [],
                    "flags_refreshed_count": 4,
                },
            )
            analysis.assert_not_called()
            self.assertEqual(result["analysis_path"], "quick")
            self.assertEqual(_pending_ids(root), set())

    def test_llm_failure_keeps_pending_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_urgent(root)
            _write_ctx(root, [{"id": "1", "folder": "INBOX"}])

            def add_two(state_root, *_a, **_k):
                _write_ctx(Path(state_root), [
                    {"id": "1", "folder": "INBOX"},
                    {"id": "2", "folder": "INBOX"},
                ])
                return {
                    "status": "ok",
                    "generated_at": "now",
                    "new_envelope_count": 1,
                    "new_envelope_ids": [["INBOX", "2"]],
                }

            fail, _ = self._sync(
                root,
                "daytime-sync",
                add_two,
                mock.Mock(return_value={"ok": False, "error": "LLM timed out", "analyzed_ids": []}),
            )
            self.assertIn("analysis", fail["degraded"])
            self.assertEqual(_pending_ids(root), {("INBOX", "2")})

            retry, analysis = self._sync(
                root,
                "daytime-sync",
                {"status": "noop", "generated_at": "now", "new_envelope_count": 0, "new_envelope_ids": []},
                mock.Mock(return_value={"ok": True, "analyzed_ids": [["INBOX", "2"]]}),
            )
            self.assertEqual(retry["analysis_path"], "incremental")
            analysis.assert_called_once()
            self.assertEqual(_pending_ids(root), set())

    def test_skipped_analysis_does_not_ack_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_urgent(root)
            _write_ctx(root, [{"id": "2", "folder": "INBOX"}])
            cli._save_pending(root, {("INBOX", "2")}, {"INBOX": 1})
            _write_watermarks(root, 1)
            result, analysis = self._sync(
                root,
                "daytime-sync",
                {"status": "noop", "generated_at": "now", "new_envelope_count": 0, "new_envelope_ids": []},
                mock.Mock(return_value={
                    "ok": True,
                    "skipped": True,
                    "reason": "no-new-threads",
                    "analyzed_ids": [["INBOX", "2"]],
                }),
            )
            self.assertEqual(result["analysis_path"], "incremental")
            analysis.assert_called_once()
            self.assertEqual(_pending_ids(root), {("INBOX", "2")})

    def test_budget_overflow_does_not_batch_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_urgent(root)
            _write_ctx(root, [
                {"id": "1", "folder": "INBOX"},
                {"id": "2", "folder": "INBOX"},
                {"id": "3", "folder": "INBOX"},
            ])
            cli._save_pending(root, {("INBOX", "2"), ("INBOX", "3")}, {"INBOX": 1})
            _write_watermarks(root, 1)
            result, analysis = self._sync(
                root,
                "daytime-sync",
                {"status": "noop", "generated_at": "now", "new_envelope_count": 0, "new_envelope_ids": []},
                mock.Mock(return_value={"ok": True, "analyzed_ids": [["INBOX", "2"]]}),
            )
            self.assertEqual(result["analysis_path"], "incremental")
            self.assertEqual(analysis.call_args.kwargs.get("only_ids"), {("INBOX", "2"), ("INBOX", "3")})
            self.assertEqual(_pending_ids(root), {("INBOX", "3")})

    def test_uidvalidity_change_drops_old_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_urgent(root)
            _write_ctx(root, [{"id": "9", "folder": "INBOX"}])
            cli._save_pending(root, {("INBOX", "9")}, {"INBOX": 1})
            _write_watermarks(root, 99)
            result, analysis = self._sync(
                root,
                "daytime-sync",
                {"status": "noop", "generated_at": "now", "new_envelope_count": 0, "new_envelope_ids": []},
            )
            analysis.assert_not_called()
            self.assertEqual(result["analysis_path"], "skip")
            self.assertEqual(_pending_ids(root), set())

    def test_window_prune_drops_ids_outside_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_urgent(root)
            _write_ctx(root, [{"id": "1", "folder": "INBOX"}])
            cli._save_pending(root, {("INBOX", "1"), ("INBOX", "99")}, {"INBOX": 1})
            _write_watermarks(root, 1)
            result, analysis = self._sync(
                root,
                "daytime-sync",
                {"status": "noop", "generated_at": "now", "new_envelope_count": 0, "new_envelope_ids": []},
                mock.Mock(return_value={"ok": True, "analyzed_ids": [["INBOX", "1"]]}),
            )
            self.assertEqual(analysis.call_args.kwargs.get("only_ids"), {("INBOX", "1")})
            self.assertEqual(_pending_ids(root), set())
            self.assertEqual(result["pending_analysis_count"], 0)

    def test_account_pending_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root_a = base / "a"
            root_b = base / "b"
            for root in (root_a, root_b):
                _write_urgent(root)
                _write_ctx(root, [{"id": "1", "folder": "INBOX"}])

            def add_two(state_root, *_a, **_k):
                _write_ctx(Path(state_root), [
                    {"id": "1", "folder": "INBOX"},
                    {"id": "2", "folder": "INBOX"},
                ])
                return {
                    "status": "ok",
                    "generated_at": "now",
                    "new_envelope_count": 1,
                    "new_envelope_ids": [["INBOX", "2"]],
                }

            def fake_root(account_id=None):
                return root_a if str(account_id) == "acct-a" else root_b

            run_analysis = mock.Mock(return_value={"ok": True, "analyzed_ids": []})
            with mock.patch.object(cli, "_account_root", side_effect=fake_root), \
                 mock.patch("twinbox_core.config.resolve_imap_config", return_value={"host": "h", "login": "u"}), \
                 mock.patch("twinbox_core.config.default_account_id", return_value="acct-a"), \
                 mock.patch("twinbox_core.runs.append_run", return_value={}), \
                 mock.patch("twinbox_core.imap_fetch.fetch_incremental", side_effect=add_two), \
                 mock.patch("twinbox_core.analyze.run_analysis", run_analysis), \
                 mock.patch("twinbox_core.pulse.write_activity_pulse", side_effect=lambda r, **_k: _fake_pulse(r)):
                cli.cmd_sync("quick-refresh", account_id="acct-a")
            self.assertEqual(_pending_ids(root_a), {("INBOX", "2")})
            self.assertEqual(_pending_ids(root_b), set())


if __name__ == "__main__":
    unittest.main()
