from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from twinbox_core.orchestration import (
    CLI_ENTRYPOINT,
    LEGACY_ENTRYPOINT,
    contract_payload,
    dispatch_bridge_event,
    get_phase_contract,
    get_scheduled_job,
    parse_bridge_event_text,
    poll_bridge_events,
    run_scheduled_job,
    render_contract_text,
    resolve_roots,
    run_steps,
)


class OrchestrationTest(unittest.TestCase):
    def setUp(self) -> None:
        # tests/test_orchestration.py -> repo root is parents[1]
        self.repo_root = Path(__file__).resolve().parents[1]

    def test_resolve_roots_default_points_at_repo_with_scripts(self) -> None:
        import os

        old = os.environ.pop("TWINBOX_CODE_ROOT", None)
        try:
            code_root, _state = resolve_roots(None)
            self.assertTrue((code_root / "scripts" / "phase4_loading.sh").is_file())
        finally:
            if old is not None:
                os.environ["TWINBOX_CODE_ROOT"] = old

    def test_contract_payload_exposes_cli_entrypoints(self) -> None:
        payload = contract_payload(self.repo_root, self.repo_root, phase=None, serial_phase4=False)

        self.assertEqual(payload["entrypoints"]["cli"], CLI_ENTRYPOINT)
        self.assertEqual(payload["entrypoints"]["legacy_fallback"], LEGACY_ENTRYPOINT)
        self.assertEqual(len(payload["phases"]), 4)
        self.assertNotIn("gastown_adapter", payload["phases"][3])

    def test_phase4_defaults_to_parallel_step(self) -> None:
        phase4 = get_phase_contract(4)

        parallel_steps = [step.id for step in phase4.selected_steps(serial_phase4=False)]
        serial_steps = [step.id for step in phase4.selected_steps(serial_phase4=True)]

        self.assertEqual(parallel_steps, ["loading", "parallel-thinking"])
        self.assertEqual(serial_steps, ["loading", "thinking"])

    def test_run_steps_dry_run_uses_shared_cli_contract(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = run_steps(
                self.repo_root,
                self.repo_root,
                phase=4,
                dry_run=True,
                serial_phase4=False,
            )

        self.assertEqual(exit_code, 0)
        output = buffer.getvalue()
        self.assertIn("Phase 4 Loading", output)
        self.assertIn("phase4_thinking_parallel.sh", output)

    def test_render_contract_text_mentions_cli_surface(self) -> None:
        rendered = render_contract_text(self.repo_root, self.repo_root, phase=2, serial_phase4=False)

        self.assertIn("Twinbox Orchestration Contract", rendered)
        self.assertIn(CLI_ENTRYPOINT, rendered)
        self.assertIn("Phase 2 - Persona Inference", rendered)

    def test_get_scheduled_job_exposes_daytime_sync_contract(self) -> None:
        job = get_scheduled_job("daytime-sync")

        self.assertEqual(job.id, "daytime-sync")
        self.assertTrue(job.updates_dedupe)
        self.assertFalse(job.archive_on_success)

    def test_run_scheduled_job_daytime_dry_run_returns_notify_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            exit_code, payload = run_scheduled_job(
                self.repo_root,
                temp_root,
                job_id="daytime-sync",
                event_source="system-event",
                dry_run=True,
                top_k=3,
                retry_once=True,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["job"], "daytime-sync")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["notify_payload"]["summary"], "dry-run")
        self.assertIsNone(payload["artifact_paths"]["schedule_log"])

    def test_run_scheduled_job_daytime_persists_log_and_dedupe(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            raw_dir = temp_root / "runtime/validation/phase-1/raw"
            raw_dir.mkdir(parents=True)
            recent = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(hours=1)).isoformat(timespec="seconds")
            (raw_dir / "envelopes-merged.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "1",
                            "folder": "INBOX",
                            "subject": "项目A资源申请",
                            "date": recent,
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            completed = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": "ok", "stderr": ""},
            )()
            with patch("twinbox_core.orchestration.subprocess.run", return_value=completed):
                exit_code, payload = run_scheduled_job(
                    self.repo_root,
                    temp_root,
                    job_id="daytime-sync",
                    event_source="system-event",
                    dry_run=False,
                    top_k=3,
                    retry_once=True,
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue((temp_root / "runtime/context/activity-pulse-state.json").is_file())
            self.assertTrue((temp_root / "runtime/audit/schedule-runs.jsonl").is_file())
            self.assertTrue((temp_root / "runtime/validation/phase-4/activity-pulse.json").is_file())
            self.assertEqual(payload["notify_payload"]["urgent_top_k"][0]["thread_key"], "项目a资源申请")

    def test_parse_bridge_event_json(self) -> None:
        event = parse_bridge_event_text(
            json.dumps(
                {
                    "kind": "twinbox.schedule",
                    "version": 1,
                    "job": "daytime-sync",
                    "event_source": "openclaw.system-event",
                    "top_k": 5,
                    "retry_once": False,
                },
                ensure_ascii=False,
            )
        )

        self.assertEqual(event.job_id, "daytime-sync")
        self.assertEqual(event.top_k, 5)
        self.assertFalse(event.retry_once)

    def test_parse_bridge_event_compact_text(self) -> None:
        event = parse_bridge_event_text("twinbox.schedule:nightly-full")

        self.assertEqual(event.job_id, "nightly-full")
        self.assertEqual(event.event_source, "openclaw.system-event")
        self.assertTrue(event.retry_once)

    def test_dispatch_bridge_event_dry_run_uses_embedded_schedule_contract(self) -> None:
        exit_code, payload = dispatch_bridge_event(
            self.repo_root,
            self.repo_root,
            event_text=json.dumps(
                {
                    "kind": "twinbox.schedule",
                    "job": "daytime-sync",
                    "event_source": "openclaw.system-event",
                    "top_k": 3,
                },
                ensure_ascii=False,
            ),
            dry_run=True,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["bridge_event"]["job"], "daytime-sync")
        self.assertEqual(payload["schedule"]["job"], "daytime-sync")
        self.assertEqual(payload["schedule"]["notify_payload"]["summary"], "dry-run")

    def test_poll_bridge_events_dry_run_returns_scan_summary(self) -> None:
        completed_list = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "job-1",
                                "payload": {
                                    "kind": "systemEvent",
                                    "text": '{"kind":"twinbox.schedule","job":"daytime-sync"}',
                                },
                            }
                        ]
                    }
                ),
                "stderr": "",
            },
        )()
        completed_runs = type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "entries": [
                            {
                                "jobId": "job-1",
                                "action": "finished",
                                "status": "ok",
                                "summary": '{"kind":"twinbox.schedule","job":"daytime-sync"}',
                                "runAtMs": 100,
                                "ts": 200,
                            }
                        ]
                    }
                ),
                "stderr": "",
            },
        )()

        with patch(
            "twinbox_core.openclaw_bridge.subprocess.run",
            side_effect=[completed_list, completed_runs],
        ):
            exit_code, payload = poll_bridge_events(
                self.repo_root,
                self.repo_root,
                dry_run=True,
                limit=10,
                openclaw_bin="openclaw",
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["dispatched_count"], 1)
        self.assertEqual(payload["failed_count"], 0)


if __name__ == "__main__":
    unittest.main()
