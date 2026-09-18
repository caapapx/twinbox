"""Queue visibility: complete/dismiss rebuilds pulse; latest/todo hide; inspect keeps."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from twinbox_core import cli
from twinbox_core.pulse import normalize_thread_key, write_activity_pulse


def _seed_mailbox(root: Path, *, subject: str = "Deploy review") -> str:
    """Write envelopes + urgent tag so pulse has attention + unread."""
    tk = normalize_thread_key(subject)
    env = {
        "id": "7",
        "folder": "INBOX",
        "subject": subject,
        "date": "2030-01-10T12:00:00+08:00",
        "flags": [],
        "from_addr": "boss@example.com",
        "recipient_role": "to",
    }
    raw_dir = root / "runtime" / "validation" / "phase-1" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "envelopes-merged.json").write_text(
        json.dumps([env], ensure_ascii=False), encoding="utf-8"
    )
    ctx = root / "runtime" / "context" / "phase1-context.json"
    ctx.parent.mkdir(parents=True, exist_ok=True)
    ctx.write_text(
        json.dumps({"envelopes": [env], "sampled_bodies": {}}, ensure_ascii=False),
        encoding="utf-8",
    )
    urgent = root / "runtime" / "validation" / "phase-4" / "daily-urgent.yaml"
    urgent.parent.mkdir(parents=True, exist_ok=True)
    urgent.write_text(
        f"generated_at: '2030-01-10T08:00:00+08:00'\n"
        f"daily_urgent:\n  - thread_key: '{tk}'\n    why: need reply\n    queue_tags: [urgent]\n",
        encoding="utf-8",
    )
    return tk


class TestQueueVisibility(unittest.TestCase):
    def test_complete_hides_from_latest_and_todo_keeps_inspect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tk = _seed_mailbox(root)
            payload, _ = write_activity_pulse(root)
            # Force a known generated_at so we can assert preserve
            pulse_path = root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
            data = json.loads(pulse_path.read_text(encoding="utf-8"))
            data["generated_at"] = "2030-01-09T10:00:00+08:00"
            pulse_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            prior_at = "2030-01-09T10:00:00+08:00"

            with mock.patch.object(cli, "_account_root", return_value=root), \
                 mock.patch.object(cli, "_resolved_account_id", return_value="default"):
                before = cli.cmd_latest_mail(unread_only=True)
                self.assertTrue(before.get("ok"))
                self.assertTrue(any(t.get("thread_key") == tk for t in before.get("threads") or []))

                todo_before = cli.cmd_todo()
                self.assertTrue(any(t.get("thread_key") == tk for t in todo_before.get("needs_attention") or []))

                result = cli.cmd_queue_action("complete", tk, reason="done")
                self.assertTrue(result.get("ok"))
                self.assertTrue(result.get("pulse_updated"))

                after = cli.cmd_latest_mail(unread_only=True)
                self.assertFalse(any(t.get("thread_key") == tk for t in after.get("threads") or []))
                self.assertEqual(after.get("generated_at"), prior_at)

                todo_after = cli.cmd_todo()
                self.assertFalse(
                    any(t.get("thread_key") == tk for t in todo_after.get("needs_attention") or [])
                )

                inspect = cli.cmd_thread_inspect("deploy")
                self.assertTrue(inspect.get("ok"))
                self.assertTrue(any(t.get("thread_key") == tk for t in inspect.get("results") or []))

    def test_lineage_survives_queue_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tk = _seed_mailbox(root)
            payload, path = write_activity_pulse(root)
            payload.update({
                "generated_at": "2030-01-09T10:00:00+08:00",
                "source_account": "acct-a",
                "stale_analysis": True,
                "analysis_generated_at": "2030-01-09T08:00:00+08:00",
                "fetch_at": "2030-01-09T09:00:00+08:00",
            })
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            path.touch()
            from twinbox_core.runs import account_freshness
            with mock.patch.object(cli, "_account_root", return_value=root), \
                 mock.patch.object(cli, "_resolved_account_id", return_value="acct-a"):
                cli.cmd_queue_action("dismiss", tk, reason="later")
                after = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(after.get("generated_at"), "2030-01-09T10:00:00+08:00")
                self.assertEqual(after.get("source_account"), "acct-a")
                self.assertTrue(after.get("stale_analysis"))
                self.assertEqual(after.get("analysis_generated_at"), "2030-01-09T08:00:00+08:00")
                self.assertEqual(after.get("fetch_at"), "2030-01-09T09:00:00+08:00")
                fresh = account_freshness(root)
                self.assertEqual(fresh["last_fetch_at"], "2030-01-09T09:00:00+08:00")
                self.assertEqual(fresh["last_analysis_at"], "2030-01-09T08:00:00+08:00")
                self.assertEqual(fresh["last_pulse_at"], "2030-01-09T10:00:00+08:00")
                cli.cmd_queue_action("restore", tk)
                todo = cli.cmd_todo()
                self.assertTrue(any(t.get("thread_key") == tk for t in todo.get("needs_attention") or []))

    def test_pulse_write_failure_keeps_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tk = _seed_mailbox(root)
            write_activity_pulse(root)
            path = root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
            before = path.read_text(encoding="utf-8")
            with mock.patch.object(cli, "_account_root", return_value=root), \
                 mock.patch.object(cli, "_resolved_account_id", return_value="default"), \
                 mock.patch("twinbox_core.imap_fetch._write_json", side_effect=OSError("disk")):
                result = cli.cmd_queue_action("complete", tk, reason="done")
            self.assertTrue(result.get("ok"))
            self.assertFalse(result.get("pulse_updated"))
            self.assertEqual(result.get("pulse_error"), "OSError")
            self.assertEqual(path.read_text(encoding="utf-8"), before)
            with mock.patch.object(cli, "_account_root", return_value=root), \
                 mock.patch.object(cli, "_resolved_account_id", return_value="default"):
                after = cli.cmd_latest_mail(unread_only=True)
                self.assertFalse(any(t.get("thread_key") == tk for t in after.get("threads") or []))

    def test_projection_error_is_diagnosed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_mailbox(root)
            with mock.patch("twinbox_core.project.attach_projections", side_effect=RuntimeError("boom")):
                payload, _ = write_activity_pulse(root)
            self.assertEqual(payload.get("diagnostics", {}).get("projection_error"), "RuntimeError")
            self.assertIn("needs_attention", payload)

    def test_queue_rebuild_waits_for_sync_publish(self) -> None:
        import threading
        import time
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tk = _seed_mailbox(root)
            write_activity_pulse(root)
            started = threading.Event()
            from twinbox_core import pulse as pulse_mod
            real_commit = pulse_mod.commit_activity_pulse

            def slow_commit(*args, **kwargs):
                started.set()
                time.sleep(0.15)
                return real_commit(*args, **kwargs)

            errors: list[str] = []

            def sync_publish():
                try:
                    with mock.patch.object(pulse_mod, "commit_activity_pulse", slow_commit):
                        pulse_mod.write_activity_pulse(root)
                except Exception as exc:
                    errors.append(str(exc))

            t = threading.Thread(target=sync_publish)
            t.start()
            self.assertTrue(started.wait(1.0))
            with mock.patch.object(cli, "_account_root", return_value=root), \
                 mock.patch.object(cli, "_resolved_account_id", return_value="default"):
                cli.cmd_queue_action("complete", tk, reason="done")
            t.join(2.0)
            self.assertFalse(t.is_alive())
            self.assertEqual(errors, [])
            data = json.loads(
                (root / "runtime" / "validation" / "phase-4" / "activity-pulse.json").read_text()
            )
            attention = [row.get("thread_key") for row in data.get("needs_attention") or []]
            self.assertNotIn(tk, attention)


if __name__ == "__main__":
    unittest.main()
