"""Offline gate for the optional WeKnora retrieval experiment.

This runner deliberately has no provider client and never reads a mailbox.  It
compares two already-executed, bounded search result sets over exactly thirty
anonymised, human-labelled queries: ten keyword, ten semantic, and ten
classification-filtered.  A synthetic dry run can validate the harness, but it
is explicitly not eligible to make an enable/ROI decision.
"""
from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import re
import statistics
import time
from typing import Any

GROUPS = ("keyword", "semantic", "classification")
CASES_PER_GROUP = 10
TOTAL_CASES = len(GROUPS) * CASES_PER_GROUP
PROVENANCE = frozenset({"human_gold", "synthetic_dry_run"})
_FILTER_FIELDS = frozenset({"status", "primary_event_type", "tags", "axes"})
_OPAQUE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
LIVE_GATE_FIELDS = (
    "adr_004_revision",
    "dedicated_kb_revision",
    "min_privilege_key_revision",
    "retention_policy_revision",
    "pre_search_acl_revision",
)
_UNASSIGNED_LIVE_GATES = frozenset({"", "unassigned", "unavailable", "pending"})


def _require_opaque_reference(value: str, *, field: str, query_id: str) -> None:
    """Reject source locators from the anonymous evaluation protocol."""
    if not _OPAQUE_REFERENCE.fullmatch(value) or "@" in value or "/" in value or "\\" in value:
        raise ValueError(f"{query_id}: {field} must contain only opaque references")


@dataclass(frozen=True)
class EvaluationCase:
    """One anonymised, pre-labelled retrieval query.

    ``query`` is sent only to the supplied runners; reports contain its stable
    ``query_id`` instead, so persisted results do not accidentally become a new
    corpus of business text.  Both reference sets use opaque TwinBox mail refs.
    """

    query_id: str
    query: str
    group: str
    allowed_mail_refs: frozenset[str]
    relevant_mail_refs: frozenset[str]
    classification_filter: Mapping[str, object] | None = None


@dataclass(frozen=True)
class EvaluationSet:
    """The fixed test set and its evidence tier."""

    provenance: str
    cases: tuple[EvaluationCase, ...]


SearchRunner = Callable[[EvaluationCase], Mapping[str, object]]


def _references(value: object, *, field: str, query_id: str) -> frozenset[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError(f"{query_id}: {field} must be an array of opaque references")
    refs = frozenset(value)
    if not refs or any(not isinstance(ref, str) or not ref.strip() for ref in refs):
        raise ValueError(f"{query_id}: {field} must contain non-empty string references")
    for ref in refs:
        _require_opaque_reference(ref, field=field, query_id=query_id)
    return refs


def _validate_filter(value: Mapping[str, object] | None, *, query_id: str, group: str) -> None:
    if group == "classification" and not value:
        raise ValueError(f"{query_id}: classification_filter is required for classification queries")
    if value is None:
        return
    if not isinstance(value, Mapping) or not set(value).issubset(_FILTER_FIELDS):
        raise ValueError(f"{query_id}: classification_filter contains unsupported fields")


def validate_evaluation_set(evaluation_set: EvaluationSet) -> None:
    """Fail closed unless this is the frozen 30-query comparison shape."""
    if evaluation_set.provenance not in PROVENANCE:
        raise ValueError("provenance must be human_gold or synthetic_dry_run")
    if len(evaluation_set.cases) != TOTAL_CASES:
        raise ValueError(f"evaluation set must contain exactly {TOTAL_CASES} cases")

    ids: set[str] = set()
    groups: Counter[str] = Counter()
    for case in evaluation_set.cases:
        if not isinstance(case.query_id, str) or not case.query_id.strip() or case.query_id in ids:
            raise ValueError("query_id values must be unique non-empty strings")
        _require_opaque_reference(case.query_id, field="query_id", query_id=case.query_id)
        ids.add(case.query_id)
        if not isinstance(case.query, str) or not case.query.strip() or len(case.query) > 512:
            raise ValueError(f"{case.query_id}: query must be a bounded non-empty string")
        if case.group not in GROUPS:
            raise ValueError(f"{case.query_id}: group must be one of {', '.join(GROUPS)}")
        allowed = _references(case.allowed_mail_refs, field="allowed_mail_refs", query_id=case.query_id)
        relevant = _references(case.relevant_mail_refs, field="relevant_mail_refs", query_id=case.query_id)
        if not relevant.issubset(allowed):
            raise ValueError(f"{case.query_id}: relevant_mail_refs must be a subset of allowed_mail_refs")
        _validate_filter(case.classification_filter, query_id=case.query_id, group=case.group)
        groups[case.group] += 1

    if {group: groups[group] for group in GROUPS} != {group: CASES_PER_GROUP for group in GROUPS}:
        raise ValueError(f"evaluation set must contain exactly {CASES_PER_GROUP} cases for each group")


def _live_gates_accepted(live_gates: Mapping[str, object] | None) -> bool:
    """Human gold is not enough to enable WeKnora or claim ROI.

    ADR-004, dedicated KB, min-privilege key, retention and pre-search ACL
    must each carry an owner-signed opaque revision. Missing, pending,
    unassigned or unavailable revisions stay fail-closed.
    """
    if live_gates is None:
        return False
    if not isinstance(live_gates, Mapping) or set(live_gates) != set(LIVE_GATE_FIELDS):
        raise ValueError("live_gates must contain only the ADR/KB/key/retention/ACL revisions")
    accepted = True
    for field in LIVE_GATE_FIELDS:
        revision = live_gates[field]
        if not isinstance(revision, str):
            raise ValueError(f"{field} must be an opaque revision")
        token = revision.strip()
        if token in _UNASSIGNED_LIVE_GATES:
            accepted = False
            continue
        _require_opaque_reference(token, field=field, query_id="live-gates")
    return accepted


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, int(len(ordered) * percentile + 0.999999) - 1)
    return round(ordered[index], 3)


def _metrics(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    recalls = [float(row["recall_at_5"]) for row in rows]
    latencies = [float(row["latency_ms"]) for row in rows]
    costs = [float(row["cost_usd"]) for row in rows]
    return {
        "query_count": len(rows),
        "recall_at_5": round(statistics.fmean(recalls), 6) if recalls else 0.0,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "mean": round(statistics.fmean(latencies), 3) if latencies else 0.0,
        },
        "cost_usd": {
            "total": round(sum(costs), 6),
            "mean": round(statistics.fmean(costs), 6) if costs else 0.0,
        },
        "unauthorized_hit_count": sum(int(row["unauthorized_hit_count"]) for row in rows),
    }


def _bounded_number(value: object, *, field: str, query_id: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{query_id}: {field} must be a non-negative number")
    return float(value)


def _run_one(runner: SearchRunner, case: EvaluationCase) -> dict[str, object]:
    started = time.perf_counter()
    response = runner(case)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if not isinstance(response, Mapping):
        raise ValueError(f"{case.query_id}: runner must return a mapping")
    raw_hits = response.get("hits")
    if not isinstance(raw_hits, list):
        raise ValueError(f"{case.query_id}: runner response must contain a hits array")

    first_five: list[str] = []
    for raw_hit in raw_hits:
        if not isinstance(raw_hit, Mapping):
            raise ValueError(f"{case.query_id}: each hit must be a mapping")
        mail_ref = raw_hit.get("mail_ref")
        if not isinstance(mail_ref, str) or not mail_ref.strip():
            raise ValueError(f"{case.query_id}: each hit needs a non-empty mail_ref")
        _require_opaque_reference(mail_ref, field="runner mail_ref", query_id=case.query_id)
        if mail_ref not in first_five and len(first_five) < 5:
            first_five.append(mail_ref)

    returned = frozenset(first_five)
    authorized = returned.intersection(case.allowed_mail_refs)
    relevant = authorized.intersection(case.relevant_mail_refs)
    reported_latency = response.get("latency_ms", elapsed_ms)
    reported_cost = response.get("cost_usd", 0.0)
    return {
        "recall_at_5": len(relevant) / len(case.relevant_mail_refs),
        "latency_ms": _bounded_number(reported_latency, field="latency_ms", query_id=case.query_id),
        "cost_usd": _bounded_number(reported_cost, field="cost_usd", query_id=case.query_id),
        "unauthorized_hit_count": len(returned - case.allowed_mail_refs),
    }


def evaluate_retrieval(
    evaluation_set: EvaluationSet,
    *,
    baseline: SearchRunner,
    candidate: SearchRunner,
    live_gates: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Compare a frozen legacy/sidecar baseline and optional candidate.

    Results are intentionally score-agnostic: raw scores from distinct backends
    cannot be mixed.  Only opaque source references, latency, bounded reported
    cost and each runner's isolated Recall@5 are evaluated.
    """
    validate_evaluation_set(evaluation_set)
    baseline_rows: list[dict[str, object]] = []
    candidate_rows: list[dict[str, object]] = []
    per_query: list[dict[str, object]] = []

    for case in evaluation_set.cases:
        old = _run_one(baseline, case)
        new = _run_one(candidate, case)
        baseline_rows.append({"group": case.group, **old})
        candidate_rows.append({"group": case.group, **new})
        per_query.append({
            "query_id": case.query_id,
            "group": case.group,
            "baseline": old,
            "candidate": new,
        })

    def grouped(rows: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
        return {
            group: _metrics([row for row in rows if row["group"] == group])
            for group in GROUPS
        }

    baseline_groups = grouped(baseline_rows)
    candidate_groups = grouped(candidate_rows)
    baseline_overall = _metrics(baseline_rows)
    candidate_overall = _metrics(candidate_rows)
    comparison_groups = {
        group: {
            "baseline_recall_at_5": baseline_groups[group]["recall_at_5"],
            "candidate_recall_at_5": candidate_groups[group]["recall_at_5"],
            "delta_recall_at_5": round(
                float(candidate_groups[group]["recall_at_5"]) - float(baseline_groups[group]["recall_at_5"]), 6
            ),
        }
        for group in GROUPS
    }

    reasons = [
        f"candidate_recall_below_baseline:{group}"
        for group in GROUPS
        if float(candidate_groups[group]["recall_at_5"]) + 1e-12 < float(baseline_groups[group]["recall_at_5"])
    ]
    if int(candidate_overall["unauthorized_hit_count"]) > 0:
        reasons.append("candidate_returned_unauthorized_hits")

    live_accepted = _live_gates_accepted(live_gates)
    if evaluation_set.provenance != "human_gold":
        gate = {
            "status": "not_decision_eligible",
            "decision_eligible": False,
            "roi_eligible": False,
            "reasons": ["fixture_not_human_gold"],
        }
    elif not live_accepted:
        gate = {
            "status": "not_decision_eligible",
            "decision_eligible": False,
            "roi_eligible": False,
            "reasons": ["live_gates_not_accepted", *reasons],
        }
    else:
        gate = {
            "status": "pass" if not reasons else "fail",
            "decision_eligible": True,
            "roi_eligible": False,
            "reasons": reasons,
        }

    return {
        "schema_version": "1.0",
        "fixture": {
            "case_count": len(evaluation_set.cases),
            "groups": {group: sum(case.group == group for case in evaluation_set.cases) for group in GROUPS},
            "provenance": evaluation_set.provenance,
        },
        "baseline": {"overall": baseline_overall, "groups": baseline_groups},
        "candidate": {"overall": candidate_overall, "groups": candidate_groups},
        "comparison": {
            "overall": {
                "baseline_recall_at_5": baseline_overall["recall_at_5"],
                "candidate_recall_at_5": candidate_overall["recall_at_5"],
                "delta_recall_at_5": round(
                    float(candidate_overall["recall_at_5"]) - float(baseline_overall["recall_at_5"]), 6
                ),
            },
            "groups": comparison_groups,
        },
        "per_query": per_query,
        "gate": gate,
    }


def load_evaluation_set(path: Path) -> EvaluationSet:
    """Load one checked-in anonymised JSON manifest; reject extra data fields."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("evaluation fixture is unreadable JSON") from exc
    if not isinstance(raw, Mapping) or set(raw) != {"schema_version", "provenance", "cases"}:
        raise ValueError("evaluation fixture must contain only schema_version, provenance and cases")
    if raw.get("schema_version") != "1.0" or not isinstance(raw.get("provenance"), str):
        raise ValueError("unsupported evaluation fixture schema")
    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("evaluation fixture cases must be an array")

    cases: list[EvaluationCase] = []
    expected_fields = {
        "query_id", "query", "group", "allowed_mail_refs", "relevant_mail_refs", "classification_filter",
    }
    for raw_case in raw_cases:
        if not isinstance(raw_case, Mapping) or set(raw_case) != expected_fields:
            raise ValueError("each evaluation case must use the approved anonymised schema")
        cases.append(EvaluationCase(
            query_id=raw_case["query_id"],
            query=raw_case["query"],
            group=raw_case["group"],
            allowed_mail_refs=_references(
                raw_case["allowed_mail_refs"], field="allowed_mail_refs", query_id=str(raw_case.get("query_id", "?")),
            ),
            relevant_mail_refs=_references(
                raw_case["relevant_mail_refs"], field="relevant_mail_refs", query_id=str(raw_case.get("query_id", "?")),
            ),
            classification_filter=raw_case["classification_filter"],
        ))
    evaluation_set = EvaluationSet(provenance=raw["provenance"], cases=tuple(cases))
    validate_evaluation_set(evaluation_set)
    return evaluation_set


def _load_results(path: Path) -> Mapping[str, Mapping[str, object]]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("result file is unreadable JSON") from exc
    if not isinstance(raw, Mapping) or any(not isinstance(key, str) or not isinstance(value, Mapping) for key, value in raw.items()):
        raise ValueError("result file must map query_id to bounded runner responses")
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True, help="anonymised 30-query JSON manifest")
    parser.add_argument("--baseline-results", type=Path, required=True, help="legacy/sidecar result JSON")
    parser.add_argument("--candidate-results", type=Path, required=True, help="candidate result JSON")
    parser.add_argument(
        "--live-gates",
        type=Path,
        help="opaque ADR/KB/key/retention/ACL revision JSON; omitted keeps enablement closed",
    )
    args = parser.parse_args()

    evaluation_set = load_evaluation_set(args.fixture)
    baseline_results = _load_results(args.baseline_results)
    candidate_results = _load_results(args.candidate_results)
    live_gates = None
    if args.live_gates is not None:
        try:
            live_gates = json.loads(args.live_gates.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("live_gates file is unreadable JSON") from exc

    def runner(results: Mapping[str, Mapping[str, object]]) -> SearchRunner:
        def run(case: EvaluationCase) -> Mapping[str, object]:
            try:
                return results[case.query_id]
            except KeyError as exc:
                raise ValueError(f"missing result for {case.query_id}") from exc
        return run

    print(json.dumps(
        evaluate_retrieval(
            evaluation_set,
            baseline=runner(baseline_results),
            candidate=runner(candidate_results),
            live_gates=live_gates,
        ),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
