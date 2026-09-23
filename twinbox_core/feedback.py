"""Authorized reverse-feedback journal for semantic cases.

Feedback is a versioned decision log.  Correction proposals do not rewrite the
classifier, and execution receipts are observations rather than proof that a
business case is complete.  Human confirmations are the only v1 feedback kind
that updates the case overlay.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Collection, Iterator

from .classification_store import (
    ClassificationStoreError,
    _atomic_write as _write_classifications,
    _write_lock as _classification_lock,
    classification_path,
    load_classifications,
)
from .evidence_contract import EvidenceContractError, SourceGrant, validate_feedback

SCHEMA_VERSION = "1.0"
MAX_DECISIONS = 1000


class FeedbackStoreError(ValueError):
    """Stable, non-sensitive feedback rejection reason."""


def feedback_path(state_root: Path) -> Path:
    return Path(state_root) / "runtime" / "context" / "feedback.json"


def feedback_audit_path(state_root: Path) -> Path:
    return Path(state_root) / "runtime" / "context" / "feedback-audit.jsonl"


def feedback_recovery_path(state_root: Path) -> Path:
    return Path(state_root) / "runtime" / "context" / "feedback-recovery.json"


def _empty(scope_id: str) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "scope_id": scope_id, "decisions": []}


def _load(state_root: Path, scope_id: str) -> dict[str, Any]:
    path = feedback_path(state_root)
    if not path.is_file():
        return _empty(scope_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise FeedbackStoreError("feedback_store_corrupt") from None
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise FeedbackStoreError("feedback_store_version_unsupported")
    if value.get("scope_id") != scope_id or not isinstance(value.get("decisions"), list):
        raise FeedbackStoreError("scope_mismatch")
    return value


@contextmanager
def _feedback_lock(state_root: Path) -> Iterator[None]:
    path = feedback_path(state_root).with_name("feedback.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _append_audit(state_root: Path, record: dict[str, Any]) -> None:
    path = feedback_audit_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # The caller holds feedback.lock, so each JSON line is serialized with the
    # decision store update.  The log is evidence, not a second state authority.
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _audit_contains(state_root: Path, decision_id: str, payload_digest: str) -> bool:
    path = feedback_audit_path(state_root)
    if not path.is_file():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        raise FeedbackStoreError("feedback_audit_unreadable") from None
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise FeedbackStoreError("feedback_audit_corrupt") from None
        if row.get("decision_id") == decision_id and row.get("payload_digest") == payload_digest:
            return True
    return False


def _ensure_audit(state_root: Path, record: dict[str, Any]) -> None:
    if not _audit_contains(state_root, record["decision_id"], record["payload_digest"]):
        _append_audit(state_root, record)


def _audit_record(stored: dict[str, Any]) -> dict[str, Any]:
    result = stored["result"]
    return {
        "decision_id": stored["decision_id"],
        "scope_id": result["scope_id"],
        "case_ref": result["case_ref"],
        "kind": result["kind"],
        "actor_ref": result["actor_ref"],
        "status": result["status"],
        "reason": result.get("reason"),
        "classification_revision": result["classification_revision"],
        "received_at": result["received_at"],
        "payload_digest": stored["payload_digest"],
    }


def _recover_pending(state_root: Path, scope_id: str) -> None:
    """Finish a single interrupted cross-file feedback update idempotently."""
    path = feedback_recovery_path(state_root)
    if not path.is_file():
        return
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise FeedbackStoreError("feedback_recovery_corrupt") from None
    if (not isinstance(journal, dict) or journal.get("schema_version") != SCHEMA_VERSION
            or journal.get("scope_id") != scope_id):
        raise FeedbackStoreError("feedback_recovery_conflict")
    stored = journal.get("stored")
    audit = journal.get("audit")
    if not isinstance(stored, dict) or not isinstance(audit, dict):
        raise FeedbackStoreError("feedback_recovery_corrupt")

    after = journal.get("classification_after")
    if after is not None:
        with _classification_lock(state_root):
            try:
                current = load_classifications(state_root, scope_id)
            except ClassificationStoreError as exc:
                raise FeedbackStoreError(str(exc)) from None
            expected_before = journal.get("classification_before_revision")
            target_revision = after.get("revision") if isinstance(after, dict) else None
            case = _find_case(current, stored["result"]["case_ref"])
            confirmation = case.get("human_confirmation") if isinstance(case, dict) else None
            already_applied = (isinstance(confirmation, dict)
                               and confirmation.get("decision_id") == stored["decision_id"]
                               and current.get("revision", -1) >= target_revision)
            if current.get("revision") == expected_before:
                _write_classifications(classification_path(state_root), after)
            elif not already_applied:
                raise FeedbackStoreError("feedback_recovery_conflict")

    store = _load(state_root, scope_id)
    existing = next((row for row in store["decisions"]
                     if isinstance(row, dict) and row.get("decision_id") == stored["decision_id"]), None)
    if existing is None:
        store["decisions"].append(stored)
        if len(store["decisions"]) > MAX_DECISIONS:
            store["decisions"] = store["decisions"][-MAX_DECISIONS:]
        _atomic_write(feedback_path(state_root), store)
    elif existing.get("payload_digest") != stored.get("payload_digest"):
        raise FeedbackStoreError("feedback_recovery_conflict")
    _ensure_audit(state_root, audit)
    path.unlink(missing_ok=True)


def _find_case(classifications: dict[str, Any], case_ref: str) -> dict[str, Any] | None:
    if case_ref in (classifications.get("tombstones") or {}):
        return None
    active = classifications.get("active_snapshot")
    rows = active.get("cases", []) if isinstance(active, dict) else []
    return next((row for row in rows if isinstance(row, dict) and row.get("case_ref") == case_ref), None)


def _record_for(payload: dict[str, Any], digest: str, *, status: str, reason: str | None,
                received_at: str, classification_revision: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "decision_id": payload["decision_id"],
        "scope_id": payload["scope_id"],
        "case_ref": payload["case_ref"],
        "expected_revision": payload["expected_revision"],
        "actor_ref": payload["actor_ref"],
        "kind": payload["kind"],
        "evidence_refs": deepcopy(payload["evidence_refs"]),
        "status": status,
        "received_at": received_at,
        "classification_revision": classification_revision,
    }
    if reason:
        result["reason"] = reason
    if payload["kind"] == "correction_proposal" and status == "accepted":
        result["proposal"] = deepcopy(payload["decision"])
        result["applied"] = False
    elif payload["kind"] == "execution_receipt" and status == "accepted":
        result["observation"] = deepcopy(payload["decision"])
        result["business_done"] = False
    elif payload["kind"] == "human_confirmation" and status == "accepted":
        result["confirmation"] = deepcopy(payload["decision"])
    return {"payload_digest": digest, "result": result}


def process_feedback(
    state_root: Path,
    payload: object,
    *,
    grant: SourceGrant,
    actor_ref: str,
    allowed_kinds: Collection[str],
) -> dict[str, Any]:
    """Validate, deduplicate and durably apply one feedback decision.

    A transient recovery journal closes the classification/feedback/audit crash
    windows without claiming a distributed transaction.
    """
    try:
        value = validate_feedback(payload, grant=grant, actor_ref=actor_ref, allowed_kinds=allowed_kinds)
    except EvidenceContractError as exc:
        raise FeedbackStoreError(str(exc)) from None

    state_root = Path(state_root)
    digest = _digest(value)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with _feedback_lock(state_root):
        _recover_pending(state_root, value["scope_id"])
        store = _load(state_root, value["scope_id"])
        existing = next(
            (row for row in store["decisions"]
             if isinstance(row, dict) and row.get("decision_id") == value["decision_id"]),
            None,
        )
        if existing is not None:
            if existing.get("payload_digest") != digest:
                raise FeedbackStoreError("decision_id_conflict")
            _ensure_audit(state_root, _audit_record(existing))
            return deepcopy(existing["result"])

        with _classification_lock(state_root):
            try:
                classifications = load_classifications(state_root, value["scope_id"])
            except ClassificationStoreError as exc:
                raise FeedbackStoreError(str(exc)) from None
            current_revision = classifications["revision"]
            case = _find_case(classifications, value["case_ref"])
            reason = None
            if case is None:
                reason = "case_not_found"
            elif value["expected_revision"] != current_revision:
                reason = "revision_conflict"

            classification_after = None
            if reason is not None:
                entry = _record_for(
                    value, digest, status="conflict", reason=reason,
                    received_at=now, classification_revision=current_revision,
                )
            else:
                next_revision = current_revision
                if value["kind"] == "human_confirmation":
                    confirmation = {
                        "decision_id": value["decision_id"],
                        "actor_ref": value["actor_ref"],
                        "confirmation": value["decision"]["confirmation"],
                        "reason": value["decision"]["reason"],
                        "evidence_refs": deepcopy(value["evidence_refs"]),
                        "observed_at": now,
                    }
                    case["human_confirmation"] = confirmation
                    next_revision += 1
                    classifications["revision"] = next_revision
                    active = classifications.get("active_snapshot")
                    if isinstance(active, dict):
                        active["revision"] = next_revision
                    classification_after = deepcopy(classifications)
                entry = _record_for(
                    value, digest, status="accepted", reason=None,
                    received_at=now, classification_revision=next_revision,
                )

            stored = {"decision_id": value["decision_id"], **entry}
            next_store = deepcopy(store)
            next_store["decisions"].append(stored)
            if len(next_store["decisions"]) > MAX_DECISIONS:
                next_store["decisions"] = next_store["decisions"][-MAX_DECISIONS:]
            audit = _audit_record(stored)
            journal = {
                "schema_version": SCHEMA_VERSION,
                "scope_id": value["scope_id"],
                "classification_before_revision": current_revision,
                "classification_after": classification_after,
                "stored": stored,
                "audit": audit,
            }
            _atomic_write(feedback_recovery_path(state_root), journal)
            if classification_after is not None:
                _write_classifications(classification_path(state_root), classification_after)
            _atomic_write(feedback_path(state_root), next_store)
            _ensure_audit(state_root, audit)
            feedback_recovery_path(state_root).unlink(missing_ok=True)
            return deepcopy(entry["result"])
