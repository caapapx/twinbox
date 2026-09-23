"""Offline, privacy-bounded event-recall gate for TwinBox adapter policy.

This evaluator deliberately has no IMAP, provider, or network client.  It
accepts an owner-approved *private* quality set that is limited to pseudonymous
envelope fields and opaque evidence references, then measures primary-event
recall on its frozen holdout split.  Its JSON report never re-emits subjects,
sender roles, mail identifiers, or other input envelope values.

A deterministic Pack mode evaluates only hard rules.  Packs with semantic event
rules are reported as incomplete rather than silently making an end-to-end
quality claim.  A separately generated, bounded prediction manifest may be
used to score an approved offline full-classifier run.

A passing recall gate is quality evidence only: it is never ROI, rollout, or
mailbox-access approval.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any

import yaml

# Allow the documented ``python tests/evaluations/<runner>.py`` form when
# launched from the repository root; pytest already supplies this path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from twinbox_core.pack import validate_pack
from twinbox_core.rules import hard_match


QUALITY_SET_SCHEMA_VERSION = "twinbox.adapter-event-recall/v1"
PREDICTION_SET_SCHEMA_VERSION = "twinbox.adapter-event-predictions/v1"
REPORT_SCHEMA_VERSION = "twinbox.adapter-event-recall-report/v1"
SUITE_ID = "TB001-event-recall"
RECALL_THRESHOLD = 0.80

_OPAQUE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_.:-]{0,95}$")
_SAFE_FOLDER = re.compile(r"^[A-Za-z0-9 ._:-]{1,64}$")
_SAFE_DATE = re.compile(r"^[0-9T:+\-Z. ]{1,64}$")
_EMAIL_LIKE = re.compile(r"[\w.+-]+@[\w.-]+")

_PRIVATE_KEYS = frozenset({
    "attachment", "attachments", "body", "content", "from_addr", "headers",
    "html", "mail_ref", "mail_refs", "message", "message_id", "raw", "snippet",
    "text", "to_addr", "to_addrs",
})
_ENVELOPE_FIELDS = frozenset({"id", "folder", "subject", "from_role", "recipient_role", "date"})
_CASE_FIELDS = frozenset({"case_id", "partition", "envelope", "expected_primary_event_type"})
_PROVENANCE_FIELDS = frozenset({"source_grant", "owner_gold", "development", "holdout"})


@dataclass(frozen=True)
class EvidenceProvenance:
    source_grant_ref: str
    owner_approval_ref: str
    development_split_ref: str
    holdout_split_ref: str


@dataclass(frozen=True)
class EventRecallCase:
    case_id: str
    partition: str
    envelope: dict[str, str]
    expected_primary_event_type: str


@dataclass(frozen=True)
class EventRecallSet:
    provenance: EvidenceProvenance
    cases: tuple[EventRecallCase, ...]


@dataclass(frozen=True)
class PredictionSet:
    run_ref: str
    predictions: dict[str, dict[str, str | None]]


def _require_mapping(value: object, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name}_must_be_mapping")
    return value


def _require_opaque_reference(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _OPAQUE_REFERENCE.fullmatch(value) or "@" in value:
        raise ValueError(f"{field}_must_be_opaque_reference")
    return value


def _require_event_type(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _EVENT_TYPE.fullmatch(value):
        raise ValueError(f"{field}_must_be_event_type")
    return value


def _reject_private_content(value: object) -> None:
    """Reject raw mail data recursively before any evaluator work is performed."""
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).lower() in _PRIVATE_KEYS:
                raise ValueError("unsafe_private_content_field")
            _reject_private_content(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_private_content(nested)


def _parse_provenance(value: object) -> EvidenceProvenance:
    provenance = _require_mapping(value, name="provenance")
    if set(provenance) != _PROVENANCE_FIELDS:
        raise ValueError("approved_provenance_shape_required")

    def approved_ref(name: str, *, ref_field: str, required_status: str) -> str:
        record = _require_mapping(provenance[name], name=name)
        if set(record) != {"status", ref_field} or record.get("status") != required_status:
            raise ValueError(f"{name}_approval_required")
        return _require_opaque_reference(record.get(ref_field), field=ref_field)

    return EvidenceProvenance(
        source_grant_ref=approved_ref("source_grant", ref_field="grant_ref", required_status="approved"),
        owner_approval_ref=approved_ref("owner_gold", ref_field="approval_ref", required_status="approved"),
        development_split_ref=approved_ref("development", ref_field="split_ref", required_status="frozen"),
        holdout_split_ref=approved_ref("holdout", ref_field="split_ref", required_status="frozen"),
    )


def _parse_envelope(value: object, *, case_id: str) -> dict[str, str]:
    envelope = _require_mapping(value, name=f"{case_id}_envelope")
    if set(envelope) != _ENVELOPE_FIELDS:
        raise ValueError("approved_envelope_schema_required")
    _reject_private_content(envelope)

    mail_id = _require_opaque_reference(envelope.get("id"), field=f"{case_id}_envelope_id")
    folder = envelope.get("folder")
    if not isinstance(folder, str) or not _SAFE_FOLDER.fullmatch(folder) or "/" in folder or "\\" in folder:
        raise ValueError(f"{case_id}_folder_must_be_safe_envelope_field")
    subject = envelope.get("subject")
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 512 or _EMAIL_LIKE.search(subject):
        raise ValueError(f"{case_id}_subject_must_be_bounded_and_email_free")
    from_role = _require_opaque_reference(envelope.get("from_role"), field=f"{case_id}_from_role")
    recipient_role = envelope.get("recipient_role")
    if recipient_role not in {"to", "cc", "bcc", "unknown"}:
        raise ValueError(f"{case_id}_recipient_role_invalid")
    date = envelope.get("date")
    if not isinstance(date, str) or not _SAFE_DATE.fullmatch(date):
        raise ValueError(f"{case_id}_date_must_be_bounded_envelope_field")
    return {
        "id": mail_id,
        "folder": folder,
        "subject": subject,
        # The runtime classifier calls this field ``from_addr``.  The quality
        # protocol accepts only an opaque pseudonymous role, never an address.
        "from_addr": from_role,
        "recipient_role": recipient_role,
        "date": date,
    }


def validate_manifest(value: object) -> EventRecallSet:
    """Parse one owner-approved private quality manifest, or fail closed."""
    _reject_private_content(value)
    manifest = _require_mapping(value, name="manifest")
    expected_fields = {"schema_version", "suite_id", "provenance", "cases"}
    if set(manifest) != expected_fields:
        raise ValueError("approved_quality_set_schema_required")
    if manifest.get("schema_version") != QUALITY_SET_SCHEMA_VERSION or manifest.get("suite_id") != SUITE_ID:
        raise ValueError("unsupported_event_recall_quality_set")

    provenance = _parse_provenance(manifest.get("provenance"))
    raw_cases = manifest.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("event_recall_cases_required")

    case_ids: set[str] = set()
    partitions: defaultdict[str, int] = defaultdict(int)
    cases: list[EventRecallCase] = []
    for index, raw_case in enumerate(raw_cases):
        case = _require_mapping(raw_case, name=f"case_{index}")
        if set(case) != _CASE_FIELDS:
            raise ValueError("approved_event_recall_case_schema_required")
        case_id = _require_opaque_reference(case.get("case_id"), field="case_id")
        if case_id in case_ids:
            raise ValueError("event_recall_case_ids_must_be_unique")
        case_ids.add(case_id)
        partition = case.get("partition")
        if partition not in {"development", "holdout"}:
            raise ValueError("event_recall_partition_invalid")
        expected = _require_event_type(case.get("expected_primary_event_type"), field=f"{case_id}_expected_type")
        cases.append(EventRecallCase(
            case_id=case_id,
            partition=partition,
            envelope=_parse_envelope(case.get("envelope"), case_id=case_id),
            expected_primary_event_type=expected,
        ))
        partitions[partition] += 1

    if not partitions["development"] or not partitions["holdout"]:
        raise ValueError("frozen_development_and_holdout_cases_required")
    return EventRecallSet(provenance=provenance, cases=tuple(cases))


def load_evaluation_set(path: Path) -> EventRecallSet:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("quality_set_is_unreadable_json") from exc
    return validate_manifest(raw)


def _condition_has_semantic_rule(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    semantic = value.get("semantic")
    return isinstance(semantic, Mapping) and bool(semantic.get("utterances"))


def hard_rule_predictions(evaluation_set: EventRecallSet, pack: Mapping[str, Any]) -> tuple[dict[str, dict[str, str | None]], int, dict[str, str | None]]:
    """Classify only the deterministic Pack path; never invoke embeddings or an LLM."""
    validated_pack = validate_pack(dict(pack))
    event_types = ((validated_pack.get("classification") or {}).get("event_types") or [])
    semantic_rule_count = 0
    for spec in event_types:
        if isinstance(spec, Mapping) and _condition_has_semantic_rule(spec.get("when", spec)):
            semantic_rule_count += 1

    predictions: dict[str, dict[str, str | None]] = {}
    for case in evaluation_set.cases:
        matches: list[dict[str, Any]] = []
        for spec in event_types:
            if not isinstance(spec, Mapping):
                continue
            condition = spec.get("when", spec)
            if hard_match(condition, case.envelope):
                matches.append({"id": spec["id"], "priority": spec.get("priority", 0)})
        matches.sort(key=lambda row: (-int(row["priority"]), str(row["id"])))
        leaders = [row for row in matches if row["priority"] == matches[0]["priority"]] if matches else []
        winner = leaders[0]["id"] if len(leaders) == 1 else None
        predictions[case.case_id] = {
            "classification_status": "classified" if winner else ("needs_confirmation" if leaders else "unknown"),
            "primary_event_type": winner,
        }
    pack_projection = {key: validated_pack.get(key) for key in ("id", "version", "fingerprint")}
    return predictions, semantic_rule_count, pack_projection


def _parse_prediction(value: object, *, case_id: str) -> dict[str, str | None]:
    prediction = _require_mapping(value, name=f"{case_id}_prediction")
    if set(prediction) != {"case_id", "classification_status", "primary_event_type"}:
        raise ValueError("approved_prediction_schema_required")
    if _require_opaque_reference(prediction.get("case_id"), field="prediction_case_id") != case_id:
        raise ValueError("prediction_case_id_mismatch")
    status = prediction.get("classification_status")
    event_type = prediction.get("primary_event_type")
    if status not in {"classified", "needs_confirmation", "unknown"}:
        raise ValueError("prediction_classification_status_invalid")
    if status == "classified":
        return {
            "classification_status": status,
            "primary_event_type": _require_event_type(event_type, field="prediction_primary_event_type"),
        }
    if event_type is not None:
        raise ValueError("non_classified_prediction_must_not_have_primary_event_type")
    return {"classification_status": status, "primary_event_type": None}


def load_prediction_set(path: Path, evaluation_set: EventRecallSet) -> PredictionSet:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("prediction_set_is_unreadable_json") from exc
    _reject_private_content(raw)
    manifest = _require_mapping(raw, name="prediction_set")
    expected_fields = {"schema_version", "suite_id", "run_ref", "predictions"}
    if set(manifest) != expected_fields:
        raise ValueError("approved_prediction_set_schema_required")
    if manifest.get("schema_version") != PREDICTION_SET_SCHEMA_VERSION or manifest.get("suite_id") != SUITE_ID:
        raise ValueError("unsupported_event_recall_prediction_set")
    run_ref = _require_opaque_reference(manifest.get("run_ref"), field="run_ref")
    raw_predictions = manifest.get("predictions")
    if not isinstance(raw_predictions, list):
        raise ValueError("event_recall_predictions_required")

    expected_ids = {case.case_id for case in evaluation_set.cases}
    parsed: dict[str, dict[str, str | None]] = {}
    for raw_prediction in raw_predictions:
        prediction = _require_mapping(raw_prediction, name="prediction")
        case_id = _require_opaque_reference(prediction.get("case_id"), field="prediction_case_id")
        if case_id in parsed or case_id not in expected_ids:
            raise ValueError("prediction_case_ids_must_match_quality_set")
        parsed[case_id] = _parse_prediction(prediction, case_id=case_id)
    if set(parsed) != expected_ids:
        raise ValueError("prediction_case_ids_must_match_quality_set")
    return PredictionSet(run_ref=run_ref, predictions=parsed)


def _partition_metrics(rows: list[dict[str, object]]) -> dict[str, object]:
    total = len(rows)
    if total == 0:
        raise ValueError("partition_cannot_be_empty")
    matched = sum(bool(row["matched"]) for row in rows)
    by_type: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_type[str(row["expected_primary_event_type"])].append(row)
    return {
        "case_count": total,
        "matched_case_count": matched,
        "primary_event_recall": round(matched / total, 6),
        "by_expected_event_type": {
            event_type: {
                "case_count": len(type_rows),
                "matched_case_count": sum(bool(row["matched"]) for row in type_rows),
                "primary_event_recall": round(sum(bool(row["matched"]) for row in type_rows) / len(type_rows), 6),
            }
            for event_type, type_rows in sorted(by_type.items())
        },
    }


def evaluate_event_recall(
    evaluation_set: EventRecallSet,
    predictions: Mapping[str, Mapping[str, str | None]],
    *,
    classifier: Mapping[str, object],
) -> dict[str, object]:
    """Score primary-event recall without returning the private input envelope."""
    expected_ids = {case.case_id for case in evaluation_set.cases}
    if set(predictions) != expected_ids:
        raise ValueError("prediction_case_ids_must_match_quality_set")

    rows: list[dict[str, object]] = []
    for case in evaluation_set.cases:
        prediction = _parse_prediction({"case_id": case.case_id, **dict(predictions[case.case_id])}, case_id=case.case_id)
        actual = prediction["primary_event_type"]
        rows.append({
            "case_id": case.case_id,
            "partition": case.partition,
            "expected_primary_event_type": case.expected_primary_event_type,
            "actual_primary_event_type": actual,
            "classification_status": prediction["classification_status"],
            "matched": actual == case.expected_primary_event_type,
        })

    development_rows = [row for row in rows if row["partition"] == "development"]
    holdout_rows = [row for row in rows if row["partition"] == "holdout"]
    development = _partition_metrics(development_rows)
    holdout = _partition_metrics(holdout_rows)

    semantic_rules_not_evaluated = bool(classifier.get("semantic_event_rule_count", 0)) and classifier.get("mode") == "hard_rules_only"
    threshold_met = float(holdout["primary_event_recall"]) >= RECALL_THRESHOLD
    if semantic_rules_not_evaluated:
        quality_gate = {
            "status": "blocked",
            "decidable": False,
            "threshold_primary_event_recall": RECALL_THRESHOLD,
            "holdout_primary_event_recall": holdout["primary_event_recall"],
            "reasons": ["semantic_event_rules_not_evaluated_offline"],
        }
    elif threshold_met:
        quality_gate = {
            "status": "pass",
            "decidable": True,
            "threshold_primary_event_recall": RECALL_THRESHOLD,
            "holdout_primary_event_recall": holdout["primary_event_recall"],
            "reasons": [],
        }
    else:
        quality_gate = {
            "status": "fail",
            "decidable": True,
            "threshold_primary_event_recall": RECALL_THRESHOLD,
            "holdout_primary_event_recall": holdout["primary_event_recall"],
            "reasons": ["holdout_primary_event_recall_below_80_percent"],
        }

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "suite_id": SUITE_ID,
        "evidence": {
            "source_grant_ref": evaluation_set.provenance.source_grant_ref,
            "owner_approval_ref": evaluation_set.provenance.owner_approval_ref,
            "development_split_ref": evaluation_set.provenance.development_split_ref,
            "holdout_split_ref": evaluation_set.provenance.holdout_split_ref,
        },
        "classifier": dict(classifier),
        "development": development,
        "holdout": holdout,
        "quality_gate": quality_gate,
        "decision_scope": {
            "roi_eligible": False,
            "rollout_eligible": False,
            "reasons": [
                "event_recall_quality_only",
                "paired_time_cost_correction_and_business_owner_evidence_required",
            ],
        },
        # Deliberately bounded: no subject, sender, folder, date, mail ID, or
        # source locator can escape through the persisted report.
        "cases": rows,
    }


def evaluate_with_pack(evaluation_set: EventRecallSet, pack: Mapping[str, Any]) -> dict[str, object]:
    predictions, semantic_rule_count, pack_projection = hard_rule_predictions(evaluation_set, pack)
    return evaluate_event_recall(
        evaluation_set,
        predictions,
        classifier={
            "mode": "hard_rules_only",
            "pack": pack_projection,
            "semantic_event_rule_count": semantic_rule_count,
        },
    )


def _load_pack(path: Path) -> Mapping[str, Any]:
    try:
        parsed = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("pack_is_unreadable_yaml") from exc
    return _require_mapping(parsed, name="pack")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quality-set", type=Path, required=True, help="owner-approved private JSON quality set")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pack", type=Path, help="Pack YAML; uses deterministic hard rules only")
    source.add_argument("--prediction-set", type=Path, help="bounded JSON output from an approved offline classifier run")
    args = parser.parse_args(argv)

    evaluation_set = load_evaluation_set(args.quality_set)
    if args.pack:
        report = evaluate_with_pack(evaluation_set, _load_pack(args.pack))
    else:
        prediction_set = load_prediction_set(args.prediction_set, evaluation_set)
        report = evaluate_event_recall(
            evaluation_set,
            prediction_set.predictions,
            classifier={"mode": "approved_offline_prediction_set", "run_ref": prediction_set.run_ref},
        )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
