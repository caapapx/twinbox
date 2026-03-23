from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from twinbox_core.evaluation import evaluate_phase4, main


class EvaluationTest(unittest.TestCase):
    def test_evaluate_phase4_metrics(self) -> None:
        predicted = {
            "daily_urgent": [{"thread_key": "A"}, {"thread_key": "B"}],
            "pending_replies": [{"thread_key": "A"}, {"thread_key": "X"}],
            "weekly_brief": {"top_actions": ["follow A", "follow C", "archive D"]},
        }
        expected = {
            "daily_urgent": [{"thread_key": "A"}, {"thread_key": "C"}],
            "pending_replies": [{"thread_key": "A"}, {"thread_key": "B"}],
            "weekly_brief": {"top_actions": ["follow A", "follow B", "follow C"]},
        }

        report = evaluate_phase4(
            predicted_payload=predicted,
            expected_payload=expected,
            contract_pass_rate=100.0,
            golden_diff_count=0,
        )

        self.assertAlmostEqual(report["urgent_f1"], 0.5)
        self.assertAlmostEqual(report["pending_f1"], 0.5)
        self.assertAlmostEqual(report["weekly_action_hit_at_5"], 2 / 3)
        self.assertEqual(report["contract_pass_rate"], 100.0)
        self.assertEqual(report["golden_diff_count"], 0)
        self.assertEqual(report["urgent_explainability"], 0.0)
        self.assertEqual(report["pending_explainability"], 0.0)

    def test_evaluate_phase4_uses_layered_weekly_action_now(self) -> None:
        predicted = {
            "daily_urgent": [],
            "pending_replies": [],
            "weekly_brief": {
                "action_now": [
                    {"thread_key": "T1", "action": "follow T1"},
                    {"thread_key": "T2", "action": "follow T2"},
                ]
            },
        }
        expected = {
            "daily_urgent": [],
            "pending_replies": [],
            "weekly_brief": {
                "action_now": [
                    {"thread_key": "T2", "action": "follow T2"},
                    {"thread_key": "T3", "action": "follow T3"},
                ]
            },
        }
        report = evaluate_phase4(
            predicted_payload=predicted,
            expected_payload=expected,
            contract_pass_rate=100.0,
            golden_diff_count=0,
        )
        self.assertAlmostEqual(report["weekly_action_hit_at_5"], 0.5)

    def test_cli_gate_fails_when_baseline_regresses_over_threshold(self) -> None:
        predicted = {
            "daily_urgent": [{"thread_key": "A", "why": "need action", "reason_code": "due_soon"}],
            "pending_replies": [{"thread_key": "A", "why": "need reply", "reason_code": "waiting_on_me"}],
            "weekly_brief": {"top_actions": ["follow A"]},
        }
        expected = {
            "daily_urgent": [{"thread_key": "A"}, {"thread_key": "B"}],
            "pending_replies": [{"thread_key": "A"}, {"thread_key": "B"}],
            "weekly_brief": {"top_actions": ["follow A", "follow B"]},
        }
        baseline_report = {
            "urgent_f1": 0.9,
            "pending_f1": 0.9,
            "weekly_action_hit_at_5": 0.9,
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pred_path = root / "pred.json"
            labels_path = root / "labels.json"
            baseline_path = root / "baseline.json"
            output_path = root / "evaluation-report.json"

            pred_path.write_text(json.dumps(predicted, ensure_ascii=False), encoding="utf-8")
            labels_path.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
            baseline_path.write_text(json.dumps(baseline_report, ensure_ascii=False), encoding="utf-8")

            exit_code = main(
                [
                    "--prediction",
                    str(pred_path),
                    "--labels",
                    str(labels_path),
                    "--baseline",
                    str(baseline_path),
                    "--max-regression-pp",
                    "1.0",
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(exit_code, 1)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertFalse(report["gate"]["passed"])
            self.assertGreaterEqual(len(report["gate"]["failures"]), 1)

    def test_cli_gate_fails_on_explainability_floor(self) -> None:
        predicted = {
            "daily_urgent": [{"thread_key": "A", "why": "need action"}],
            "pending_replies": [{"thread_key": "A", "reason_code": "waiting_on_me"}],
            "weekly_brief": {"top_actions": ["follow A"]},
        }
        expected = {
            "daily_urgent": [{"thread_key": "A"}],
            "pending_replies": [{"thread_key": "A"}],
            "weekly_brief": {"top_actions": ["follow A"]},
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pred_path = root / "pred.json"
            labels_path = root / "labels.json"
            output_path = root / "evaluation-report.json"

            pred_path.write_text(json.dumps(predicted, ensure_ascii=False), encoding="utf-8")
            labels_path.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")

            exit_code = main(
                [
                    "--prediction",
                    str(pred_path),
                    "--labels",
                    str(labels_path),
                    "--min-explainability",
                    "1.0",
                    "--output",
                    str(output_path),
                ]
            )

            self.assertEqual(exit_code, 1)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertFalse(report["gate"]["passed"])
            self.assertGreaterEqual(len(report["gate"]["failures"]), 1)


if __name__ == "__main__":
    unittest.main()
