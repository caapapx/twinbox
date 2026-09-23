"""Offline TB13 fixed-case evaluator; it never reads a mailbox or a private corpus.

TB13 maintains a stable inventory for 013's scenario regression.  Historical
cases intentionally retain opaque handles only; their evaluation remains
blocked until a business owner supplies approved, private source/gold material.
Synthetic cases exercise deterministic hard-rule classification and expose the
same classification/evidence/correction/failure report shape.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

# Allow the documented ``python tests/evaluations/<runner>.py`` form when
# launched from the repository root; pytest already supplies this path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from twinbox_core.events import classify_envelope


SCHEMA_VERSION = "tb13-cases/v1"
EVALUATION_SCHEMA_VERSION = "tb13-evaluation/v1"
HISTORY_CASE_IDS = tuple(f"TB13-H{index:02d}" for index in range(1, 15))
SYNTHETIC_CASE_IDS = tuple(f"TB13-S{index:02d}" for index in range(1, 11))
PRIVATE_CONTENT_KEYS = frozenset({
    "attachments", "attachment", "body", "content", "envelope", "headers",
    "mail_ref", "mail_refs", "message", "raw", "snippet", "text",
})


def _require_mapping(value: object, *, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name}_must_be_mapping")
    return value


def _reject_private_content(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in PRIVATE_CONTENT_KEYS:
                raise ValueError("unsafe_content_field")
            _reject_private_content(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_private_content(nested)


def validate_manifest(value: object) -> dict[str, Any]:
    """Validate the fixed TB13 inventory before executing any local fixture."""
    manifest = deepcopy(_require_mapping(value, name="manifest"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported_tb13_schema")
    if manifest.get("suite_id") != "TB13":
        raise ValueError("invalid_tb13_suite")
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError("tb13_cases_must_be_list")
    expected_ids = HISTORY_CASE_IDS + SYNTHETIC_CASE_IDS
    if [case.get("case_id") if isinstance(case, dict) else None for case in cases] != list(expected_ids):
        raise ValueError("tb13_fixed_case_ids_required")

    for index, raw in enumerate(cases):
        case = _require_mapping(raw, name=f"case_{index}")
        expected_source = "private_history" if index < len(HISTORY_CASE_IDS) else "synthetic"
        if case.get("source_kind") != expected_source:
            raise ValueError("tb13_fixed_source_kind_required")
        if expected_source == "private_history":
            _reject_private_content(case)
            if set(case) != {"case_id", "source_kind", "private_case_ref", "owner_gold_status"}:
                raise ValueError("tb13_history_case_shape_invalid")
            if not isinstance(case.get("private_case_ref"), str) or not case["private_case_ref"].strip():
                raise ValueError("tb13_private_case_ref_required")
            if case.get("owner_gold_status") not in {"pending", "approved"}:
                raise ValueError("tb13_owner_gold_status_invalid")
        else:
            if set(case) != {"case_id", "source_kind", "scenario", "expected"}:
                raise ValueError("tb13_synthetic_case_shape_invalid")
            scenario = _require_mapping(case.get("scenario"), name="tb13_scenario")
            expected = _require_mapping(case.get("expected"), name="tb13_expected")
            _require_mapping(scenario.get("pack"), name="tb13_pack")
            _require_mapping(scenario.get("envelope"), name="tb13_envelope")
            if not isinstance(expected.get("classification_status"), str):
                raise ValueError("tb13_expected_status_required")
            if "primary_event_type" not in expected:
                raise ValueError("tb13_expected_event_type_required")
    return manifest


def _historical_report(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "source_kind": "private_history",
        "classification": {"status": "not_evaluated", "reason": "private_source_and_owner_gold_required"},
        "evidence": {"status": "not_available", "reason": "private_source_and_owner_gold_required"},
        "correction": {"status": "not_observed", "reason": "private_source_and_owner_gold_required"},
        "failure": {
            "status": "blocked",
            "reason": "private_source_and_owner_gold_required",
            "decision_eligible": False,
        },
    }


def _synthetic_report(case: dict[str, Any]) -> dict[str, Any]:
    scenario = case["scenario"]
    expected = case["expected"]
    actual = classify_envelope(scenario["pack"], scenario["envelope"], Path("."))
    actual_status = actual["classification_status"]
    actual_event_type = actual["semantics"]["primary_event_type"]
    passed = (
        actual_status == expected["classification_status"]
        and actual_event_type == expected["primary_event_type"]
    )
    if passed:
        failure = {"status": "none", "reason": None, "decision_eligible": False}
    else:
        failure = {"status": "failed", "reason": "classification_mismatch", "decision_eligible": False}
    return {
        "case_id": case["case_id"],
        "source_kind": "synthetic",
        "classification": {
            "status": "pass" if passed else "fail",
            "expected_status": expected["classification_status"],
            "actual_status": actual_status,
            "expected_primary_event_type": expected["primary_event_type"],
            "actual_primary_event_type": actual_event_type,
        },
        "evidence": {
            "basis": actual["semantics"]["evidence_basis"],
            "candidate_event_types": [row["id"] for row in actual["classification_candidates"]],
            "status": "synthetic_only",
        },
        "correction": {"status": "not_observed", "reason": "synthetic_case_has_no_human_feedback"},
        "failure": failure,
    }


def evaluate(value: object) -> dict[str, Any]:
    """Return the complete per-case report without private input or ROI claims."""
    manifest = validate_manifest(value)
    reports = [
        _historical_report(case) if case["source_kind"] == "private_history" else _synthetic_report(case)
        for case in manifest["cases"]
    ]
    history_count = len(HISTORY_CASE_IDS)
    synthetic_count = len(SYNTHETIC_CASE_IDS)
    # This runner never opens the private ledger or a mailbox. A git-fixture
    # owner_gold_status=approved is not owner gold and must not zero the gap.
    private_owner_gold_missing = history_count
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "suite_id": "TB13",
        "synthetic": True,
        "summary": {
            "case_count": len(reports),
            "history_case_count": history_count,
            "synthetic_case_count": synthetic_count,
            "decision_eligible": False,
            "private_owner_gold_missing": private_owner_gold_missing,
        },
        "reports": reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "fixtures" / "tb13" / "cases.json",
    )
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    print(json.dumps(evaluate(manifest), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
