from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from twinbox_core.context_builder import run_phase2_loading, run_phase3_loading


class ContextBuilderTest(unittest.TestCase):
    def _write_phase1_inputs(self, root: Path) -> None:
        (root / "runtime/context").mkdir(parents=True, exist_ok=True)
        (root / "runtime/validation/phase-1").mkdir(parents=True, exist_ok=True)
        phase1_context = {
            "owner_domain": "example.com",
            "lookback_days": 7,
            "stats": {"folders_scanned": ["INBOX"]},
            "envelopes": [
                {
                    "id": "1",
                    "folder": "INBOX",
                    "subject": "Re: 资源申请 20260319",
                    "from_name": "Alice",
                    "from_addr": "alice@example.com",
                    "date": "2026-03-19 10:00+08:00",
                    "has_attachment": False,
                },
                {
                    "id": "2",
                    "folder": "INBOX",
                    "subject": "资源申请 20260319",
                    "from_name": "Bob",
                    "from_addr": "bob@vendor.com",
                    "date": "2026-03-18 09:00+08:00",
                    "has_attachment": True,
                },
            ],
            "sampled_bodies": {
                "1": {"subject": "Re: 资源申请 20260319", "body": "请审批资源。"},
                "2": {"subject": "资源申请 20260319", "body": "等待确认。"},
            },
        }
        intent_classification = {
            "classifications": [
                {"id": "1", "intent": "collaboration", "confidence": 0.9, "evidence": ["alice"]},
                {"id": "2", "intent": "support", "confidence": 0.5, "evidence": ["bob"]},
            ]
        }
        (root / "runtime/context/phase1-context.json").write_text(
            json.dumps(phase1_context, ensure_ascii=False),
            encoding="utf-8",
        )
        (root / "runtime/validation/phase-1/intent-classification.json").write_text(
            json.dumps(intent_classification, ensure_ascii=False),
            encoding="utf-8",
        )
        (root / "runtime/context/manual-facts.yaml").write_text(
            "facts:\n  - id: F1\n    value: owner handles approvals\n",
            encoding="utf-8",
        )
        (root / "runtime/context/manual-habits.yaml").write_text(
            "habits:\n  - id: H1\n    cadence: weekly\n",
            encoding="utf-8",
        )
        (root / "runtime/context/instance-calibration-notes.md").write_text(
            "This calibration note is long enough to be included.\n" * 4,
            encoding="utf-8",
        )

    def test_phase2_loading_writes_context_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_phase1_inputs(root)

            context = run_phase2_loading(root)

            output = json.loads(
                (root / "runtime/validation/phase-2/context-pack.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(output["enriched_samples"]), 2)
            self.assertEqual(output["mailbox_summary"]["total_envelopes"], 2)
            self.assertTrue(output["human_context"]["has_facts"])
            self.assertEqual(context["top_contacts"][0]["key"], "alice@example.com")

    def test_phase3_loading_writes_context_pack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_phase1_inputs(root)
            phase2_dir = root / "runtime/validation/phase-2"
            phase2_dir.mkdir(parents=True, exist_ok=True)
            (phase2_dir / "persona-hypotheses.yaml").write_text("persona: yes\n", encoding="utf-8")
            (phase2_dir / "business-hypotheses.yaml").write_text("business: yes\n", encoding="utf-8")

            context = run_phase3_loading(root)

            output = json.loads(
                (root / "runtime/validation/phase-3/context-pack.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(output["top_threads"]), 1)
            self.assertEqual(output["top_threads"][0]["thread_key"], "资源申请")
            self.assertEqual(output["mailbox_summary"]["total_threads"], 1)
            self.assertEqual(context["persona_summary"], "persona: yes")


if __name__ == "__main__":
    unittest.main()
