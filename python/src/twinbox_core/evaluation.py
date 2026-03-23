"""Evaluation helpers and CLI gates for Phase 4 read-only outputs."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


METRIC_KEYS = ("urgent_f1", "pending_f1", "weekly_action_hit_at_5")


class EvaluationError(RuntimeError):
    """Raised when evaluation input cannot be parsed."""


@dataclass(frozen=True)
class ClassificationMetrics:
    precision: float
    recall: float
    f1: float
    predicted_count: int
    expected_count: int
    true_positive_count: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json_object(path: Path) -> dict[str, object]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise EvaluationError(f"Expected JSON object in {path}")
    return parsed


def _normalize_phase4_payload(payload: dict[str, object]) -> dict[str, object]:
    return {
        "daily_urgent": payload.get("daily_urgent", []),
        "pending_replies": payload.get("pending_replies", []),
        "weekly_brief": payload.get("weekly_brief", {}),
    }


def load_phase4_payload(path: Path) -> dict[str, object]:
    if path.is_file():
        return _normalize_phase4_payload(_load_json_object(path))

    if path.is_dir():
        llm_response = path / "llm-response.json"
        if llm_response.is_file():
            return _normalize_phase4_payload(_load_json_object(llm_response))

        urgent_pending = path / "urgent-pending-raw.json"
        weekly_brief = path / "weekly-brief-raw.json"
        if urgent_pending.is_file() and weekly_brief.is_file():
            up = _load_json_object(urgent_pending)
            wb = _load_json_object(weekly_brief)
            return _normalize_phase4_payload(
                {
                    "daily_urgent": up.get("daily_urgent", []),
                    "pending_replies": up.get("pending_replies", []),
                    "weekly_brief": wb.get("weekly_brief", {}),
                }
            )

    raise EvaluationError(
        f"Cannot resolve Phase 4 payload from {path}. "
        "Provide a JSON file, an output dir with llm-response.json, or a dir with urgent-pending-raw.json + weekly-brief-raw.json."
    )


def _thread_set(items: object) -> set[str]:
    result: set[str] = set()
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("thread_key")
        if isinstance(key, str) and key:
            result.add(key)
    return result


def _safe_ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return numerator / denominator


def _classification_metrics(predicted: set[str], expected: set[str]) -> ClassificationMetrics:
    tp = len(predicted & expected)
    precision = _safe_ratio(tp, len(predicted))
    recall = _safe_ratio(tp, len(expected))
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return ClassificationMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        predicted_count=len(predicted),
        expected_count=len(expected),
        true_positive_count=tp,
    )


def _weekly_action_hit_at_5(predicted: object, expected: object) -> float:
    pred_actions = []
    exp_actions = []
    if isinstance(predicted, dict):
        top_actions = predicted.get("top_actions", [])
        if isinstance(top_actions, list):
            pred_actions = [entry for entry in top_actions if isinstance(entry, str)]
    if isinstance(expected, dict):
        top_actions = expected.get("top_actions", [])
        if isinstance(top_actions, list):
            exp_actions = [entry for entry in top_actions if isinstance(entry, str)]

    expected_top5 = exp_actions[:5]
    if not expected_top5:
        return 1.0
    predicted_top5 = set(pred_actions[:5])
    matched = sum(1 for entry in expected_top5 if entry in predicted_top5)
    return matched / len(expected_top5)


def evaluate_phase4(
    *,
    predicted_payload: dict[str, object],
    expected_payload: dict[str, object],
    contract_pass_rate: float,
    golden_diff_count: int,
) -> dict[str, object]:
    predicted_urgent = _thread_set(predicted_payload.get("daily_urgent", []))
    expected_urgent = _thread_set(expected_payload.get("daily_urgent", []))
    predicted_pending = _thread_set(predicted_payload.get("pending_replies", []))
    expected_pending = _thread_set(expected_payload.get("pending_replies", []))

    urgent_metrics = _classification_metrics(predicted_urgent, expected_urgent)
    pending_metrics = _classification_metrics(predicted_pending, expected_pending)
    weekly_hit = _weekly_action_hit_at_5(
        predicted_payload.get("weekly_brief", {}),
        expected_payload.get("weekly_brief", {}),
    )

    return {
        "generated_at": _now_iso(),
        "phase": "phase4",
        "urgent_f1": urgent_metrics.f1,
        "pending_f1": pending_metrics.f1,
        "weekly_action_hit_at_5": weekly_hit,
        "contract_pass_rate": contract_pass_rate,
        "golden_diff_count": int(golden_diff_count),
        "metrics": {
            "daily_urgent": {
                "precision": urgent_metrics.precision,
                "recall": urgent_metrics.recall,
                "f1": urgent_metrics.f1,
                "predicted_count": urgent_metrics.predicted_count,
                "expected_count": urgent_metrics.expected_count,
                "true_positive_count": urgent_metrics.true_positive_count,
            },
            "pending_replies": {
                "precision": pending_metrics.precision,
                "recall": pending_metrics.recall,
                "f1": pending_metrics.f1,
                "predicted_count": pending_metrics.predicted_count,
                "expected_count": pending_metrics.expected_count,
                "true_positive_count": pending_metrics.true_positive_count,
            },
            "weekly_action_hit_at_5": weekly_hit,
        },
    }


def _gate_with_baseline(
    *,
    current_report: dict[str, object],
    baseline_report: dict[str, object],
    max_regression_pp: float,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    max_drop = max_regression_pp / 100.0
    for key in METRIC_KEYS:
        current = float(current_report.get(key, 0.0) or 0.0)
        baseline = float(baseline_report.get(key, 0.0) or 0.0)
        if baseline - current > max_drop:
            failures.append(
                f"{key} regressed by {(baseline - current) * 100:.2f}pp (baseline={baseline:.4f}, current={current:.4f})"
            )
    return (not failures), failures


def _default_output_path(prediction_path: Path) -> Path:
    if prediction_path.is_dir():
        return prediction_path / "evaluation-report.json"
    return prediction_path.with_name("evaluation-report.json")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction", required=True, help="Path to prediction JSON or phase-4 output directory")
    parser.add_argument("--labels", required=True, help="Path to labeled JSON payload")
    parser.add_argument("--output", help="Output report path (default: alongside prediction)")
    parser.add_argument("--baseline", help="Optional baseline evaluation-report.json for regression gate")
    parser.add_argument("--max-regression-pp", type=float, default=1.0, help="Allowed drop against baseline in percentage points")
    parser.add_argument("--contract-pass-rate", type=float, default=100.0)
    parser.add_argument("--golden-diff-count", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        prediction_path = Path(args.prediction).expanduser()
        labels_path = Path(args.labels).expanduser()
        output_path = Path(args.output).expanduser() if args.output else _default_output_path(prediction_path)

        predicted = load_phase4_payload(prediction_path)
        expected = load_phase4_payload(labels_path)
        report = evaluate_phase4(
            predicted_payload=predicted,
            expected_payload=expected,
            contract_pass_rate=args.contract_pass_rate,
            golden_diff_count=args.golden_diff_count,
        )

        gate_passed = True
        gate_failures: list[str] = []
        if args.baseline:
            baseline_report = _load_json_object(Path(args.baseline).expanduser())
            gate_passed, gate_failures = _gate_with_baseline(
                current_report=report,
                baseline_report=baseline_report,
                max_regression_pp=args.max_regression_pp,
            )

        report["gate"] = {
            "passed": gate_passed,
            "max_regression_pp": args.max_regression_pp,
            "failures": gate_failures,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        print(
            "phase4 evaluation: "
            f"urgent_f1={report['urgent_f1']:.4f}, "
            f"pending_f1={report['pending_f1']:.4f}, "
            f"weekly_action_hit_at_5={report['weekly_action_hit_at_5']:.4f}, "
            f"gate={'pass' if gate_passed else 'fail'}"
        )
        print(f"report: {output_path}")
        return 0 if gate_passed else 1
    except (EvaluationError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
