"""Bounded client views over TwinBox-owned semantic classifications."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .classification_store import load_classifications
from .pack import classification_catalog, load_active_pack


def _project_row(case: dict[str, Any], classification: dict[str, Any], *, revision: int,
                 labels: dict[str, str], include_evidence: bool) -> dict[str, Any]:
    event_type = classification.get("primary_event_type")
    # Keep the established raw fields for old cards. Display metadata is
    # additive, and unknown future IDs remain visible instead of rejected.
    item = {
        "case_ref": case["case_ref"],
        "revision": revision,
        "status": classification.get("status", "unknown"),
        "primary_event_type": event_type,
        "tags": deepcopy(classification.get("tags") or {}),
        "axes": deepcopy(classification.get("axes") or {}),
        "display": {"event_type": labels.get(event_type, event_type) if event_type else None},
    }
    for key in ("subject", "project_ref", "reason", "human_confirmation"):
        if case.get(key) is not None:
            item[key] = deepcopy(case[key])
    if include_evidence:
        item["evidence_refs"] = deepcopy(case.get("evidence_refs") or [])
    return item


def _rows(state_root: Path, scope_id: str, *, include_evidence: bool,
          only_case_ref: str = "") -> tuple[dict[str, Any], list[dict[str, Any]]]:
    stored = load_classifications(state_root, scope_id)
    active = stored.get("active_snapshot")
    cases = active.get("cases", []) if isinstance(active, dict) else []
    classifications = active.get("classifications", []) if isinstance(active, dict) else []
    catalog = classification_catalog(load_active_pack(state_root))
    labels = {row["id"]: row["label"] for row in catalog["event_types"]}
    revision = active.get("revision") if isinstance(active, dict) else stored["revision"]

    if only_case_ref:
        case = next((row for row in cases if isinstance(row, dict)
                     and row.get("case_ref") == only_case_ref), None)
        if case is None:
            return catalog, []
        classification = next((row for row in classifications if isinstance(row, dict)
                               and row.get("case_ref") == only_case_ref), {"status": "unknown"})
        return catalog, [_project_row(case, classification, revision=revision,
                                      labels=labels, include_evidence=include_evidence)]

    by_ref = {row.get("case_ref"): row for row in classifications if isinstance(row, dict)}
    output = [
        _project_row(case, by_ref.get(case["case_ref"], {"status": "unknown"}),
                     revision=revision, labels=labels, include_evidence=include_evidence)
        for case in cases
        if isinstance(case, dict) and case.get("case_ref")
    ]
    return catalog, output


def project_semantics(
    state_root: Path,
    *,
    scope_id: str,
    action: str = "list",
    case_ref: str = "",
    include_evidence: bool = False,
) -> dict[str, Any]:
    """Return catalog/list/get views without mail locators or full content."""
    if action == "get":
        _, rows = _rows(Path(state_root), scope_id, include_evidence=include_evidence,
                        only_case_ref=case_ref)
        selected = rows[0] if rows else None
        if selected is None:
            return {"schema_version": "1.0", "scope_id": scope_id, "case": None, "error": "case_not_found"}
        return {"schema_version": "1.0", "scope_id": scope_id, "case": selected}

    catalog, rows = _rows(Path(state_root), scope_id, include_evidence=include_evidence)
    if action == "catalog":
        return {"schema_version": "1.0", "scope_id": scope_id, "catalog": catalog}
    if action != "list":
        raise ValueError("unsupported_semantic_action")
    return {"schema_version": "1.0", "scope_id": scope_id, "count": len(rows), "cases": rows}
