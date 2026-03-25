from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from twinbox_core.openclaw_bridge import (
    discover_bridge_runs,
    poll_openclaw_bridge,
)


class OpenClawBridgeTest(unittest.TestCase):
    def test_discover_bridge_runs_filters_finished_twinbox_entries(self) -> None:
        runs_payload = {
            "entries": [
                {
                    "jobId": "job-1",
                    "action": "finished",
                    "status": "ok",
                    "summary": '{"kind":"twinbox.schedule","job":"daytime-sync"}',
                    "runAtMs": 100,
                    "ts": 200,
                },
                {
                    "jobId": "job-2",
                    "action": "finished",
                    "status": "error",
                    "summary": '{"kind":"twinbox.schedule","job":"nightly-full"}',
                    "runAtMs": 101,
                    "ts": 201,
                },
                {
                    "jobId": "job-3",
                    "action": "finished",
                    "status": "ok",
                    "summary": "heartbeat-ok",
                    "runAtMs": 102,
                    "ts": 202,
                },
            ]
        }

        discovered, counters = discover_bridge_runs(runs_payload, processed_entry_keys=set())

        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0].job_id, "job-1")
        self.assertEqual(counters["scanned_entries"], 3)
        self.assertEqual(counters["ignored_entries"], 2)

    def test_poll_openclaw_bridge_dispatches_and_persists_state(self) -> None:
        jobs_payload = {
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
        runs_payload = {
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

        def fake_dispatch(event_text: str, dry_run: bool) -> tuple[int, dict[str, object]]:
            return 0, {
                "bridge_event": {"job": "daytime-sync"},
                "schedule": {"status": "success", "run_id": "sched-1"},
            }

        completed_list = type(
            "Completed",
            (),
            {"returncode": 0, "stdout": json.dumps(jobs_payload), "stderr": ""},
        )()
        completed_runs = type(
            "Completed",
            (),
            {"returncode": 0, "stdout": json.dumps(runs_payload), "stderr": ""},
        )()

        with TemporaryDirectory() as temp_dir:
            state_root = Path(temp_dir)
            with patch(
                "twinbox_core.openclaw_bridge.subprocess.run",
                side_effect=[completed_list, completed_runs],
            ):
                exit_code, payload = poll_openclaw_bridge(
                    state_root,
                    dry_run=False,
                    limit=10,
                    openclaw_bin="openclaw",
                    dispatch_event=fake_dispatch,
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["dispatched_count"], 1)
            self.assertEqual(payload["bridge_jobs"], 1)
            self.assertTrue((state_root / "runtime/context/openclaw-bridge-state.json").is_file())
            self.assertTrue((state_root / "runtime/audit/openclaw-bridge-polls.jsonl").is_file())

    def test_poll_openclaw_bridge_skips_processed_entries(self) -> None:
        jobs_payload = {
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
        runs_payload = {
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
        completed_list = type(
            "Completed",
            (),
            {"returncode": 0, "stdout": json.dumps(jobs_payload), "stderr": ""},
        )()
        completed_runs = type(
            "Completed",
            (),
            {"returncode": 0, "stdout": json.dumps(runs_payload), "stderr": ""},
        )()

        with TemporaryDirectory() as temp_dir:
            state_root = Path(temp_dir)
            state_file = state_root / "runtime/context/openclaw-bridge-state.json"
            state_file.parent.mkdir(parents=True)
            state_file.write_text(
                json.dumps({"processed_entry_keys": ["job-1|100|200"]}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch(
                "twinbox_core.openclaw_bridge.subprocess.run",
                side_effect=[completed_list, completed_runs],
            ):
                exit_code, payload = poll_openclaw_bridge(
                    state_root,
                    dry_run=False,
                    limit=10,
                    openclaw_bin="openclaw",
                    dispatch_event=lambda *_args, **_kwargs: self.fail("dispatch should not run"),
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["processed_skipped"], 1)
            self.assertEqual(payload["dispatched_count"], 0)


if __name__ == "__main__":
    unittest.main()
