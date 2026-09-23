"""Value snapshot and the embeddings_degraded status warning."""

import json
import unittest
from pathlib import Path
import tempfile

from tests.evaluations.value_replay import snapshot
from twinbox_core.cli import status_warnings


class ValueReplayTest(unittest.TestCase):
    def test_pairs_sent_headers_without_inventing_latency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = root / "runtime" / "context"
            phase4 = root / "runtime" / "validation" / "phase-4"
            ctx.mkdir(parents=True)
            phase4.mkdir(parents=True)
            (ctx / "phase1-context.json").write_text(json.dumps({
                "envelopes": [
                    {"subject": "Re: 周报", "message_id": "<a@x>"},
                    {"subject": "合同", "message_id": "<b@x>"},
                ]
            }), encoding="utf-8")
            (ctx / "sent-headers.json").write_text(json.dumps({
                "headers": [{"in_reply_to": "<a@x>", "references": "", "to": "a@x"}]
            }), encoding="utf-8")
            (phase4 / "activity-pulse.json").write_text(json.dumps({
                "needs_attention": [{"thread_key": "合同", "subject": "合同"}]
            }), encoding="utf-8")
            out = snapshot(root)
        self.assertTrue(out["ok"])
        self.assertEqual(out["owner_action_miss"], 1)
        self.assertEqual(out["push_waste"], 1)
        self.assertIsNone(out["time_to_surface"])

    def test_refuses_metrics_without_sent_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = snapshot(Path(tmp))
        self.assertFalse(out["ok"])
        self.assertEqual(out["truth"], "insufficient")

    def test_three_configs_do_not_change_the_snapshot(self):
        fixture_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "value_replay"
        names = ("none.yaml", "project.yaml", "ticket.yaml")
        blobs = [(fixture_dir / name).read_text(encoding="utf-8") for name in names]
        engine = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (Path(__file__).resolve().parents[1] / "twinbox_core").glob("*.py")
        )
        for blob in blobs:
            for line in blob.splitlines():
                if line.startswith("label:"):
                    self.assertNotIn(line.split(":", 1)[1].strip(), engine)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = root / "runtime" / "context"
            ctx.mkdir(parents=True)
            (ctx / "phase1-context.json").write_text("{}", encoding="utf-8")
            (ctx / "sent-headers.json").write_text(json.dumps({"headers": []}), encoding="utf-8")
            shots = [snapshot(root) for _ in blobs]
        self.assertEqual(shots[0], shots[1])
        self.assertEqual(shots[1], shots[2])
        self.assertEqual(shots[0]["truth"], "insufficient")

    def test_status_warns_when_embeddings_degraded(self):
        warned = status_warnings({"select": {"embeddings_degraded": True}, "run_id": "r1"}, [], [])
        quiet = status_warnings({"select": {"embeddings_degraded": False}}, [], [])
        self.assertEqual(warned[0]["embeddings_degraded"], True)
        self.assertEqual(quiet, [])


if __name__ == "__main__":
    unittest.main()
