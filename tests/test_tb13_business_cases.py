"""Failure-first tests for the fixed, privacy-safe TB13 evaluation harness."""
from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent
MODULE = runpy.run_path(str(ROOT / "evaluations" / "tb13_business_cases.py"))
MANIFEST = ROOT / "fixtures" / "tb13" / "cases.json"


def _load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_tb13_manifest_locks_the_14_history_and_10_synthetic_case_shape() -> None:
    manifest = _load_manifest()
    validated = MODULE["validate_manifest"](manifest)

    assert validated["suite_id"] == "TB13"
    assert len(validated["cases"]) == 24
    assert [case["case_id"] for case in validated["cases"]] == [
        *(f"TB13-H{index:02d}" for index in range(1, 15)),
        *(f"TB13-S{index:02d}" for index in range(1, 11)),
    ]
    assert [case["source_kind"] for case in validated["cases"][:14]] == ["private_history"] * 14
    assert [case["source_kind"] for case in validated["cases"][14:]] == ["synthetic"] * 10


def test_tb13_history_inventory_is_opaque_and_rejects_mail_content_fields() -> None:
    manifest = _load_manifest()
    history = manifest["cases"][0]

    assert set(history) == {"case_id", "source_kind", "private_case_ref", "owner_gold_status"}
    assert not any(key in history for key in ("body", "snippet", "text", "attachments", "mail_ref"))

    unsafe = _load_manifest()
    unsafe["cases"][0]["body"] = "must never enter a repo fixture"
    with pytest.raises(ValueError, match="unsafe_content_field"):
        MODULE["validate_manifest"](unsafe)


def test_tb13_reports_every_case_and_fails_closed_without_private_owner_gold() -> None:
    result = MODULE["evaluate"](_load_manifest())

    assert result["schema_version"] == "tb13-evaluation/v1"
    assert result["summary"] == {
        "case_count": 24,
        "history_case_count": 14,
        "synthetic_case_count": 10,
        "decision_eligible": False,
        "private_owner_gold_missing": 14,
    }
    assert len(result["reports"]) == 24
    for report in result["reports"]:
        assert set(report) == {"case_id", "source_kind", "classification", "evidence", "correction", "failure"}

    historical = result["reports"][0]
    assert historical["classification"]["status"] == "not_evaluated"
    assert historical["evidence"]["status"] == "not_available"
    assert historical["correction"]["status"] == "not_observed"
    assert historical["failure"] == {
        "status": "blocked",
        "reason": "private_source_and_owner_gold_required",
        "decision_eligible": False,
    }


def test_tb13_synthetic_cases_exercise_deterministic_classification_and_expose_failures() -> None:
    result = MODULE["evaluate"](_load_manifest())
    reports = {row["case_id"]: row for row in result["reports"]}

    priority = reports["TB13-S01"]
    assert priority["classification"] == {
        "status": "pass",
        "expected_status": "classified",
        "actual_status": "classified",
        "expected_primary_event_type": "synthetic.decision",
        "actual_primary_event_type": "synthetic.decision",
    }
    assert priority["evidence"]["basis"] == "explicit"
    assert priority["failure"] == {"status": "none", "reason": None, "decision_eligible": False}

    conflict = reports["TB13-S02"]
    assert conflict["classification"]["actual_status"] == "needs_confirmation"
    assert conflict["classification"]["actual_primary_event_type"] is None

    failed_manifest = _load_manifest()
    failed_manifest["cases"][14]["expected"]["primary_event_type"] = "synthetic.wrong"
    failed = MODULE["evaluate"](failed_manifest)
    failed_row = next(row for row in failed["reports"] if row["case_id"] == "TB13-S01")
    assert failed_row["classification"]["status"] == "fail"
    assert failed_row["failure"] == {
        "status": "failed",
        "reason": "classification_mismatch",
        "decision_eligible": False,
    }


def test_tb13_fixture_gold_flags_do_not_count_as_owner_gold() -> None:
    manifest = _load_manifest()
    for case in manifest["cases"][:14]:
        case["owner_gold_status"] = "approved"

    result = MODULE["evaluate"](manifest)

    assert result["summary"]["private_owner_gold_missing"] == 14
    assert result["summary"]["decision_eligible"] is False
    historical = result["reports"][0]
    assert historical["classification"]["status"] == "not_evaluated"
    assert historical["failure"] == {
        "status": "blocked",
        "reason": "private_source_and_owner_gold_required",
        "decision_eligible": False,
    }
