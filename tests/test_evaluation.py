"""Tests for twinbox_core.evaluation — Phase 4 metric computation and CLI gate.

Coverage areas
--------------
- F1 metric computation (urgent, pending) including boundary / degenerate cases
- Weekly action hit@5 for both flat and layered (action_now) structures
- CLI gate: regression detection, explainability floor, gate-passes case
- Explainability coverage computation
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from twinbox_core.evaluation import evaluate_phase4, main


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _make_eval(
    urgent_pred=None,
    urgent_exp=None,
    pending_pred=None,
    pending_exp=None,
    weekly_pred=None,
    weekly_exp=None,
    contract_pass_rate=100.0,
    golden_diff_count=0,
):
    """Build evaluate_phase4 inputs with sensible defaults."""
    predicted = {
        "daily_urgent": urgent_pred or [],
        "pending_replies": pending_pred or [],
        "weekly_brief": weekly_pred or {"top_actions": []},
    }
    expected = {
        "daily_urgent": urgent_exp or [],
        "pending_replies": pending_exp or [],
        "weekly_brief": weekly_exp or {"top_actions": []},
    }
    return evaluate_phase4(
        predicted_payload=predicted,
        expected_payload=expected,
        contract_pass_rate=contract_pass_rate,
        golden_diff_count=golden_diff_count,
    )


# ---------------------------------------------------------------------------
# F1 metric computation
# ---------------------------------------------------------------------------


class TestF1Metrics:
    """urgent_f1 and pending_f1 computed correctly across cases."""

    def test_partial_overlap(self):
        """predict=[A,B] expect=[A,C] → precision=0.5 recall=0.5 → F1=0.5."""
        report = _make_eval(
            urgent_pred=[{"thread_key": "A"}, {"thread_key": "B"}],
            urgent_exp=[{"thread_key": "A"}, {"thread_key": "C"}],
            pending_pred=[{"thread_key": "A"}, {"thread_key": "X"}],
            pending_exp=[{"thread_key": "A"}, {"thread_key": "B"}],
        )
        assert pytest.approx(report["urgent_f1"]) == 0.5
        assert pytest.approx(report["pending_f1"]) == 0.5

    def test_perfect_match_gives_f1_of_1(self):
        """When predicted == expected, F1 must be 1.0."""
        report = _make_eval(
            urgent_pred=[{"thread_key": "A"}, {"thread_key": "B"}],
            urgent_exp=[{"thread_key": "A"}, {"thread_key": "B"}],
        )
        assert pytest.approx(report["urgent_f1"]) == 1.0

    def test_zero_overlap_gives_f1_of_0(self):
        """No correct predictions → F1 = 0.0."""
        report = _make_eval(
            urgent_pred=[{"thread_key": "X"}],
            urgent_exp=[{"thread_key": "Y"}],
        )
        assert pytest.approx(report["urgent_f1"]) == 0.0

    def test_empty_predicted_gives_f1_of_0(self):
        """Empty predicted set → precision undefined → F1 = 0.0, no crash."""
        report = _make_eval(
            urgent_pred=[],
            urgent_exp=[{"thread_key": "A"}],
        )
        assert report["urgent_f1"] == 0.0

    def test_empty_expected_gives_f1_of_0(self):
        """Empty expected set → recall undefined → F1 = 0.0, no crash."""
        report = _make_eval(
            urgent_pred=[{"thread_key": "A"}],
            urgent_exp=[],
        )
        assert report["urgent_f1"] == 0.0

    def test_both_empty_gives_f1_of_1(self):
        """Both empty → _safe_ratio(0,0)=1.0 by design (perfect agreement on nothing).

        This is intentional: if nothing was expected and nothing was predicted,
        the system is correct. Callers should treat all-zero counts as a
        data-quality warning, not a regression signal.
        """
        report = _make_eval(urgent_pred=[], urgent_exp=[])
        assert report["urgent_f1"] == 1.0


# ---------------------------------------------------------------------------
# Weekly action hit@5
# ---------------------------------------------------------------------------


class TestWeeklyActionHit:
    """weekly_action_hit_at_5 computed for both flat and layered structures."""

    def test_flat_top_actions(self):
        report = _make_eval(
            weekly_pred={"top_actions": ["follow A", "follow C", "archive D"]},
            weekly_exp={"top_actions": ["follow A", "follow B", "follow C"]},
        )
        assert pytest.approx(report["weekly_action_hit_at_5"]) == 2 / 3

    def test_layered_action_now(self):
        """action_now list takes priority over top_actions for hit computation."""
        report = _make_eval(
            weekly_pred={"action_now": [
                {"thread_key": "T1", "action": "follow T1"},
                {"thread_key": "T2", "action": "follow T2"},
            ]},
            weekly_exp={"action_now": [
                {"thread_key": "T2", "action": "follow T2"},
                {"thread_key": "T3", "action": "follow T3"},
            ]},
        )
        assert pytest.approx(report["weekly_action_hit_at_5"]) == 0.5

    def test_empty_weekly_is_perfect_agreement(self):
        """Empty predicted + empty expected = 1.0 by _safe_ratio design (see TestF1Metrics)."""
        report = _make_eval(weekly_pred={"top_actions": []}, weekly_exp={"top_actions": []})
        assert report["weekly_action_hit_at_5"] == 1.0


# ---------------------------------------------------------------------------
# Explainability coverage
# ---------------------------------------------------------------------------


class TestExplainabilityCoverage:
    """urgent_explainability and pending_explainability computed correctly."""

    def test_items_with_why_and_reason_code_score_1(self):
        report = _make_eval(
            urgent_pred=[{"thread_key": "A", "why": "need action", "reason_code": "due_soon"}],
            urgent_exp=[{"thread_key": "A"}],
        )
        assert pytest.approx(report["urgent_explainability"]) == 1.0

    def test_items_without_explainability_fields_score_0(self):
        report = _make_eval(
            urgent_pred=[{"thread_key": "A"}, {"thread_key": "B"}],
            urgent_exp=[{"thread_key": "A"}, {"thread_key": "B"}],
        )
        assert report["urgent_explainability"] == 0.0

    def test_partial_explainability(self):
        """Only items with BOTH why and reason_code count."""
        report = _make_eval(
            urgent_pred=[
                {"thread_key": "A", "why": "reason", "reason_code": "rc"},  # ✓
                {"thread_key": "B", "why": "reason"},                        # ✗ no reason_code
                {"thread_key": "C"},                                          # ✗ neither
            ],
            urgent_exp=[{"thread_key": "A"}, {"thread_key": "B"}, {"thread_key": "C"}],
        )
        assert pytest.approx(report["urgent_explainability"]) == 1 / 3


# ---------------------------------------------------------------------------
# CLI gate — file I/O integration tests
# ---------------------------------------------------------------------------


class TestCliGate:
    """main() gate passes/fails based on regression thresholds."""

    def _run_gate(self, tmp_path: Path, predicted: dict, expected: dict,
                  baseline: dict | None = None, extra_args: list | None = None) -> tuple[int, dict]:
        pred_path = tmp_path / "pred.json"
        labels_path = tmp_path / "labels.json"
        output_path = tmp_path / "report.json"
        pred_path.write_text(json.dumps(predicted, ensure_ascii=False), encoding="utf-8")
        labels_path.write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")

        args = ["--prediction", str(pred_path), "--labels", str(labels_path),
                "--output", str(output_path)]

        if baseline is not None:
            baseline_path = tmp_path / "baseline.json"
            baseline_path.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
            args += ["--baseline", str(baseline_path), "--max-regression-pp", "1.0"]

        if extra_args:
            args += extra_args

        exit_code = main(args)
        report = json.loads(output_path.read_text(encoding="utf-8"))
        return exit_code, report

    def test_gate_fails_on_regression_above_threshold(self, tmp_path):
        """Gate must exit 1 when metrics regress more than 1pp from baseline."""
        predicted = {
            "daily_urgent": [{"thread_key": "A", "why": "w", "reason_code": "rc"}],
            "pending_replies": [{"thread_key": "A", "why": "w", "reason_code": "rc"}],
            "weekly_brief": {"top_actions": ["follow A"]},
        }
        expected = {
            "daily_urgent": [{"thread_key": "A"}, {"thread_key": "B"}],
            "pending_replies": [{"thread_key": "A"}, {"thread_key": "B"}],
            "weekly_brief": {"top_actions": ["follow A", "follow B"]},
        }
        baseline = {"urgent_f1": 0.9, "pending_f1": 0.9, "weekly_action_hit_at_5": 0.9}

        exit_code, report = self._run_gate(tmp_path, predicted, expected, baseline)
        assert exit_code == 1
        assert report["gate"]["passed"] is False
        assert len(report["gate"]["failures"]) >= 1

    def test_gate_passes_when_no_regression(self, tmp_path):
        """Gate must exit 0 when predicted == expected (perfect score, no regression)."""
        perfect = {
            "daily_urgent": [{"thread_key": "A"}, {"thread_key": "B"}],
            "pending_replies": [{"thread_key": "A"}],
            "weekly_brief": {"top_actions": ["follow A"]},
        }
        baseline = {"urgent_f1": 0.5, "pending_f1": 0.5, "weekly_action_hit_at_5": 0.5}

        exit_code, report = self._run_gate(tmp_path, perfect, perfect, baseline)
        assert exit_code == 0
        assert report["gate"]["passed"] is True

    def test_gate_fails_on_explainability_floor(self, tmp_path):
        """--min-explainability 1.0 must fail when any item lacks why/reason_code."""
        predicted = {
            "daily_urgent": [{"thread_key": "A", "why": "need action"}],  # missing reason_code
            "pending_replies": [{"thread_key": "A", "reason_code": "waiting"}],  # missing why
            "weekly_brief": {"top_actions": ["follow A"]},
        }
        expected = {
            "daily_urgent": [{"thread_key": "A"}],
            "pending_replies": [{"thread_key": "A"}],
            "weekly_brief": {"top_actions": ["follow A"]},
        }
        exit_code, report = self._run_gate(
            tmp_path, predicted, expected,
            extra_args=["--min-explainability", "1.0"],
        )
        assert exit_code == 1
        assert report["gate"]["passed"] is False
        assert len(report["gate"]["failures"]) >= 1

    def test_report_always_includes_required_fields(self, tmp_path):
        """Evaluation report must include all standard metric fields."""
        data = {
            "daily_urgent": [{"thread_key": "A"}],
            "pending_replies": [],
            "weekly_brief": {"top_actions": []},
        }
        _, report = self._run_gate(tmp_path, data, data)
        required = {"urgent_f1", "pending_f1", "weekly_action_hit_at_5",
                    "contract_pass_rate", "golden_diff_count",
                    "urgent_explainability", "pending_explainability", "gate"}
        missing = required - report.keys()
        assert not missing, f"Report missing fields: {missing}"
