from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from twinbox_core.phase1_intent import IntentRunConfig, run_phase1_intent


class Phase1IntentTest(unittest.TestCase):
    def test_dry_run_writes_placeholder_outputs(self) -> None:
        context = {
            "envelopes": [
                {
                    "id": "1",
                    "folder": "INBOX",
                    "from_name": "Alice",
                    "from_addr": "alice@example.com",
                    "subject": "Hello",
                    "date": "2026-03-20 10:00+08:00",
                    "has_attachment": False,
                },
                {
                    "id": "2",
                    "folder": "INBOX",
                    "from_name": "Bob",
                    "from_addr": "bob@example.com",
                    "subject": "Invoice",
                    "date": "2026-03-20 11:00+08:00",
                    "has_attachment": True,
                },
            ],
            "sampled_bodies": {
                "1": {"body": "Need help with account access."},
                "2": {"body": "Please find the invoice attached."},
            },
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context_path = root / "phase1-context.json"
            output_dir = root / "phase-1"
            context_path.write_text(json.dumps(context), encoding="utf-8")

            result = run_phase1_intent(
                IntentRunConfig(
                    context_path=context_path,
                    output_dir=output_dir,
                    batch_size=1,
                    dry_run=True,
                    env_file=None,
                    model_override=None,
                )
            )

            output = json.loads((output_dir / "intent-classification.json").read_text(encoding="utf-8"))
            report = (output_dir / "intent-report.md").read_text(encoding="utf-8")

            self.assertTrue(result["dry_run"])
            self.assertEqual(output["stats"]["total_envelopes"], 2)
            self.assertEqual(len(output["classifications"]), 2)
            self.assertEqual(output["distribution"]["human"], 2)
            self.assertIn("Phase 1 Intent Classification Report", report)


if __name__ == "__main__":
    unittest.main()
