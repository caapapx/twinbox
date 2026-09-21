"""TDD coverage for the offline, non-live WeKnora retrieval evaluation harness."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys

import pytest

_MODULE_PATH = Path(__file__).parent / "evaluations" / "weknora_retrieval.py"
_SPEC = importlib.util.spec_from_file_location("weknora_retrieval_evaluation", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

GROUPS = _MODULE.GROUPS
EvaluationCase = _MODULE.EvaluationCase
EvaluationSet = _MODULE.EvaluationSet
evaluate_retrieval = _MODULE.evaluate_retrieval
validate_evaluation_set = _MODULE.validate_evaluation_set


def _cases(*, provenance: str = "synthetic_dry_run") -> EvaluationSet:
    cases = []
    for group in GROUPS:
        for ordinal in range(10):
            mail_ref = f"mail-{group}-{ordinal}"
            cases.append(
                EvaluationCase(
                    query_id=f"{group}-{ordinal:02d}",
                    query=f"anonymous {group} query {ordinal}",
                    group=group,
                    allowed_mail_refs=frozenset({mail_ref}),
                    relevant_mail_refs=frozenset({mail_ref}),
                    classification_filter=(
                        {"primary_event_type": "contract.review"}
                        if group == "classification"
                        else None
                    ),
                )
            )
    return EvaluationSet(provenance=provenance, cases=tuple(cases))


def _result_for(case: EvaluationCase, *, latency_ms: float, cost_usd: float) -> Mapping[str, object]:
    return {
        "hits": [{"mail_ref": next(iter(case.relevant_mail_refs))}],
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
    }


def test_evaluator_compares_fixed_30_anonymous_cases_by_group_without_claiming_roi():
    fixture = _cases()

    result = evaluate_retrieval(
        fixture,
        baseline=lambda case: _result_for(case, latency_ms=5, cost_usd=0.01),
        candidate=lambda case: _result_for(case, latency_ms=8, cost_usd=0.02),
    )

    assert result["fixture"] == {
        "case_count": 30,
        "groups": {"classification": 10, "keyword": 10, "semantic": 10},
        "provenance": "synthetic_dry_run",
    }
    assert result["baseline"]["overall"]["recall_at_5"] == 1.0
    assert result["candidate"]["overall"]["recall_at_5"] == 1.0
    assert result["candidate"]["overall"]["cost_usd"]["total"] == 0.6
    assert result["comparison"]["groups"]["semantic"]["candidate_recall_at_5"] == 1.0
    assert result["gate"] == {
        "status": "not_decision_eligible",
        "decision_eligible": False,
        "roi_eligible": False,
        "reasons": ["fixture_not_human_gold"],
    }
    assert all("query" not in row for row in result["per_query"])


def _accepted_live_gates() -> dict[str, str]:
    return {
        "adr_004_revision": "adr-v1",
        "dedicated_kb_revision": "kb-v1",
        "min_privilege_key_revision": "key-v1",
        "retention_policy_revision": "retention-v1",
        "pre_search_acl_revision": "acl-v1",
    }


def test_human_gold_without_live_gates_is_not_enablement_or_roi_eligible():
    fixture = _cases(provenance="human_gold")

    result = evaluate_retrieval(
        fixture,
        baseline=lambda case: _result_for(case, latency_ms=5, cost_usd=0.01),
        candidate=lambda case: _result_for(case, latency_ms=8, cost_usd=0.02),
    )

    assert result["gate"] == {
        "status": "not_decision_eligible",
        "decision_eligible": False,
        "roi_eligible": False,
        "reasons": ["live_gates_not_accepted"],
    }


def test_pending_live_gates_keep_human_gold_not_decision_eligible():
    fixture = _cases(provenance="human_gold")
    pending = {field: "pending" for field in _accepted_live_gates()}

    result = evaluate_retrieval(
        fixture,
        baseline=lambda case: _result_for(case, latency_ms=5, cost_usd=0.01),
        candidate=lambda case: _result_for(case, latency_ms=8, cost_usd=0.02),
        live_gates=pending,
    )

    assert result["gate"]["decision_eligible"] is False
    assert result["gate"]["roi_eligible"] is False
    assert result["gate"]["reasons"] == ["live_gates_not_accepted"]


def test_live_gates_reject_agent_os_control_plane_fields():
    fixture = _cases(provenance="human_gold")
    gates = {**_accepted_live_gates(), "work_context_id": "wc-1"}

    with pytest.raises(ValueError, match="live_gates must contain only"):
        evaluate_retrieval(
            fixture,
            baseline=lambda case: _result_for(case, latency_ms=5, cost_usd=0.01),
            candidate=lambda case: _result_for(case, latency_ms=8, cost_usd=0.02),
            live_gates=gates,
        )


def test_evaluator_marks_security_and_group_recall_failures_when_human_gold_is_supplied():
    fixture = _cases(provenance="human_gold")

    def candidate(case: EvaluationCase) -> Mapping[str, object]:
        if case.group == "keyword":
            return {"hits": [], "latency_ms": 9, "cost_usd": 0.03}
        if case.group == "semantic" and case.query_id.endswith("00"):
            return {
                "hits": [
                    {"mail_ref": "outside-grant"},
                    {"mail_ref": next(iter(case.relevant_mail_refs))},
                ],
                "latency_ms": 9,
                "cost_usd": 0.03,
            }
        return _result_for(case, latency_ms=9, cost_usd=0.03)

    result = evaluate_retrieval(
        fixture,
        baseline=lambda case: _result_for(case, latency_ms=5, cost_usd=0.01),
        candidate=candidate,
        live_gates=_accepted_live_gates(),
    )

    assert result["candidate"]["groups"]["keyword"]["recall_at_5"] == 0.0
    assert result["candidate"]["overall"]["unauthorized_hit_count"] == 1
    assert result["gate"]["status"] == "fail"
    assert result["gate"]["decision_eligible"] is True
    assert result["gate"]["roi_eligible"] is False
    assert result["gate"]["reasons"] == [
        "candidate_recall_below_baseline:keyword",
        "candidate_returned_unauthorized_hits",
    ]


def test_evaluator_rejects_nonopaque_references_from_fixture_and_runner():
    fixture = _cases()
    invalid_cases = list(fixture.cases)
    invalid_cases[0] = replace(
        invalid_cases[0],
        allowed_mail_refs=frozenset({"reviewer@example.com"}),
        relevant_mail_refs=frozenset({"reviewer@example.com"}),
    )
    with pytest.raises(ValueError, match="opaque references"):
        validate_evaluation_set(EvaluationSet(provenance="human_gold", cases=tuple(invalid_cases)))

    def nonopaque_candidate(case: EvaluationCase) -> Mapping[str, object]:
        if case.query_id == fixture.cases[0].query_id:
            return {"hits": [{"mail_ref": "reviewer@example.com"}], "latency_ms": 8, "cost_usd": 0.02}
        return _result_for(case, latency_ms=8, cost_usd=0.02)

    with pytest.raises(ValueError, match="runner mail_ref must contain only opaque references"):
        evaluate_retrieval(
            fixture,
            baseline=lambda case: _result_for(case, latency_ms=5, cost_usd=0.01),
            candidate=nonopaque_candidate,
        )


def test_fixed_eval_set_rejects_non_30_case_sets_and_bad_classification_contracts():
    fixture = _cases()
    with pytest.raises(ValueError, match="exactly 30"):
        validate_evaluation_set(EvaluationSet(provenance="human_gold", cases=fixture.cases[:-1]))

    invalid = list(fixture.cases)
    invalid[20] = EvaluationCase(
        query_id="classification-invalid",
        query="anonymous classification query",
        group="classification",
        allowed_mail_refs=frozenset({"mail-classification-invalid"}),
        relevant_mail_refs=frozenset({"mail-classification-invalid"}),
        classification_filter=None,
    )
    with pytest.raises(ValueError, match="classification_filter"):
        validate_evaluation_set(EvaluationSet(provenance="human_gold", cases=tuple(invalid)))


def test_loader_accepts_only_anonymised_fixed_manifest(tmp_path: Path):
    fixture = _cases(provenance="human_gold")
    manifest = {
        "schema_version": "1.0",
        "provenance": fixture.provenance,
        "cases": [
            {
                "query_id": case.query_id,
                "query": case.query,
                "group": case.group,
                "allowed_mail_refs": sorted(case.allowed_mail_refs),
                "relevant_mail_refs": sorted(case.relevant_mail_refs),
                "classification_filter": case.classification_filter,
            }
            for case in fixture.cases
        ],
    }
    path = tmp_path / "anonymous-gold.json"
    import json

    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert _MODULE.load_evaluation_set(path) == fixture

    manifest["cases"][0]["body"] = "must not be admitted"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="approved anonymised schema"):
        _MODULE.load_evaluation_set(path)
