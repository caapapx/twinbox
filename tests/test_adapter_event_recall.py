"""Privacy and quality-gate tests for the owner-approved 001 recall harness."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy

import pytest


ROOT = Path(__file__).resolve().parent
MODULE = runpy.run_path(str(ROOT / "evaluations" / "adapter_event_recall.py"))


def _pack(*, semantic: bool = False) -> dict:
    risk_when: dict[str, object] = {"subject_regex": "risk"}
    if semantic:
        risk_when["semantic"] = {"utterances": ["incident"]}
    return {
        "id": "owner-quality-pack",
        "version": "1.0.0",
        "classification": {
            "event_types": [
                {"id": "risk", "label": "Risk", "priority": 30, "when": risk_when},
                {"id": "weekly_report", "label": "Weekly", "priority": 20, "when": {"subject_regex": "weekly"}},
                {"id": "plan_change", "label": "Plan", "priority": 10, "when": {"subject_regex": "plan"}},
            ]
        },
    }


def _case(case_id: str, partition: str, subject: str, expected: str) -> dict:
    return {
        "case_id": case_id,
        "partition": partition,
        "envelope": {
            "id": f"opaque-{case_id.lower()}",
            "folder": "INBOX",
            "subject": subject,
            "from_role": "delivery-owner",
            "recipient_role": "to",
            "date": "2026-09-21T10:00:00+08:00",
        },
        "expected_primary_event_type": expected,
    }


def _manifest() -> dict:
    return {
        "schema_version": "twinbox.adapter-event-recall/v1",
        "suite_id": "TB001-event-recall",
        "provenance": {
            "source_grant": {"status": "approved", "grant_ref": "grant-001"},
            "owner_gold": {"status": "approved", "approval_ref": "owner-gold-001"},
            "development": {"status": "frozen", "split_ref": "dev-split-001"},
            "holdout": {"status": "frozen", "split_ref": "holdout-split-001"},
        },
        "cases": [
            _case("DEV-01", "development", "risk triage", "risk"),
            _case("HO-01", "holdout", "risk review", "risk"),
            _case("HO-02", "holdout", "weekly delivery", "weekly_report"),
            _case("HO-03", "holdout", "plan update", "plan_change"),
            _case("HO-04", "holdout", "risk escalation", "risk"),
            _case("HO-05", "holdout", "weekly checkpoint", "weekly_report"),
        ],
    }


def test_owner_approved_frozen_holdout_pack_run_reports_event_recall_without_envelope_leakage() -> None:
    evaluation_set = MODULE["validate_manifest"](_manifest())
    report = MODULE["evaluate_with_pack"](evaluation_set, _pack())

    assert report["schema_version"] == "twinbox.adapter-event-recall-report/v1"
    assert report["development"]["primary_event_recall"] == 1.0
    assert report["holdout"]["primary_event_recall"] == 1.0
    assert report["holdout"]["by_expected_event_type"]["risk"] == {
        "case_count": 2,
        "matched_case_count": 2,
        "primary_event_recall": 1.0,
    }
    assert report["quality_gate"] == {
        "status": "pass",
        "decidable": True,
        "threshold_primary_event_recall": 0.8,
        "holdout_primary_event_recall": 1.0,
        "reasons": [],
    }
    assert report["decision_scope"]["roi_eligible"] is False
    assert report["decision_scope"]["rollout_eligible"] is False
    assert set(report["cases"][0]) == {
        "case_id", "partition", "expected_primary_event_type", "actual_primary_event_type",
        "classification_status", "matched",
    }
    serialized = json.dumps(report)
    assert "risk triage" not in serialized
    assert "delivery-owner" not in serialized
    assert "opaque-dev-01" not in serialized


def test_holdout_recall_uses_only_frozen_holdout_and_80_percent_is_the_boundary() -> None:
    evaluation_set = MODULE["validate_manifest"](_manifest())
    predictions, _, _ = MODULE["hard_rule_predictions"](evaluation_set, _pack())
    predictions["DEV-01"] = {"classification_status": "unknown", "primary_event_type": None}
    predictions["HO-01"] = {"classification_status": "unknown", "primary_event_type": None}
    report = MODULE["evaluate_event_recall"](
        evaluation_set,
        predictions,
        classifier={"mode": "approved_offline_prediction_set", "run_ref": "offline-run-001"},
    )

    assert report["development"]["primary_event_recall"] == 0.0
    assert report["holdout"]["primary_event_recall"] == 0.8
    assert report["quality_gate"]["status"] == "pass"
    assert report["quality_gate"]["decidable"] is True

    predictions["HO-02"] = {"classification_status": "unknown", "primary_event_type": None}
    failed = MODULE["evaluate_event_recall"](
        evaluation_set,
        predictions,
        classifier={"mode": "approved_offline_prediction_set", "run_ref": "offline-run-002"},
    )
    assert failed["holdout"]["primary_event_recall"] == 0.6
    assert failed["quality_gate"] == {
        "status": "fail",
        "decidable": True,
        "threshold_primary_event_recall": 0.8,
        "holdout_primary_event_recall": 0.6,
        "reasons": ["holdout_primary_event_recall_below_80_percent"],
    }


def test_hard_rule_runner_blocks_a_full_quality_claim_when_semantic_event_rules_exist() -> None:
    evaluation_set = MODULE["validate_manifest"](_manifest())
    report = MODULE["evaluate_with_pack"](evaluation_set, _pack(semantic=True))

    assert report["classifier"]["mode"] == "hard_rules_only"
    assert report["classifier"]["semantic_event_rule_count"] == 1
    assert report["quality_gate"] == {
        "status": "blocked",
        "decidable": False,
        "threshold_primary_event_recall": 0.8,
        "holdout_primary_event_recall": 1.0,
        "reasons": ["semantic_event_rules_not_evaluated_offline"],
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda manifest: manifest.__setitem__("synthetic_only", True), "approved_quality_set_schema_required"),
        (lambda manifest: manifest["cases"][0].__setitem__("body", "raw mail"), "unsafe_private_content_field"),
        (lambda manifest: manifest["cases"][0]["envelope"].__setitem__("from_addr", "person@example.com"), "unsafe_private_content_field"),
        (lambda manifest: manifest["cases"][0]["envelope"].__setitem__("subject", "mail person@example.com"), "subject_must_be_bounded_and_email_free"),
        (lambda manifest: manifest["cases"][0].__setitem__("case_id", "case/with/path"), "case_id_must_be_opaque_reference"),
        (lambda manifest: manifest["provenance"]["owner_gold"].__setitem__("status", "pending"), "owner_gold_approval_required"),
        (lambda manifest: manifest["provenance"]["holdout"].__setitem__("status", "open"), "holdout_approval_required"),
    ],
)
def test_quality_manifest_rejects_synthetic_private_or_unfrozen_inputs(mutation, message: str) -> None:
    invalid = copy.deepcopy(_manifest())
    mutation(invalid)
    with pytest.raises(ValueError, match=message):
        MODULE["validate_manifest"](invalid)


def test_prediction_manifest_requires_the_exact_approved_case_set_and_never_accepts_mail_fields(tmp_path: Path) -> None:
    quality_path = tmp_path / "quality.json"
    quality_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    evaluation_set = MODULE["load_evaluation_set"](quality_path)
    predictions, _, _ = MODULE["hard_rule_predictions"](evaluation_set, _pack())
    prediction_manifest = {
        "schema_version": "twinbox.adapter-event-predictions/v1",
        "suite_id": "TB001-event-recall",
        "run_ref": "offline-full-run-001",
        "predictions": [
            {"case_id": case_id, **prediction}
            for case_id, prediction in sorted(predictions.items())
        ],
    }
    prediction_path = tmp_path / "predictions.json"
    prediction_path.write_text(json.dumps(prediction_manifest), encoding="utf-8")
    loaded = MODULE["load_prediction_set"](prediction_path, evaluation_set)
    assert loaded.run_ref == "offline-full-run-001"
    assert loaded.predictions == predictions

    prediction_manifest["predictions"][0]["subject"] = "must never be accepted"
    prediction_path.write_text(json.dumps(prediction_manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="approved_prediction_schema_required"):
        MODULE["load_prediction_set"](prediction_path, evaluation_set)


def test_quality_manifest_requires_both_frozen_partitions() -> None:
    invalid = _manifest()
    invalid["cases"] = [case for case in invalid["cases"] if case["partition"] != "holdout"]
    with pytest.raises(ValueError, match="frozen_development_and_holdout_cases_required"):
        MODULE["validate_manifest"](invalid)
