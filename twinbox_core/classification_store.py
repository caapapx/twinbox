"""Versioned, account-local case classification snapshots for feature 013.

The file is a derived projection, not a mail-fetch watermark and not an ACL.
Writes are serialized per state root and published with one atomic replace.  This
module deliberately makes no cross-file transaction claim.
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
from typing import Any, Iterable, Iterator

SCHEMA_VERSION = "1.0"
_ALLOWED_STATUS = {"unknown", "candidate", "classified", "needs_confirmation", "stale"}


class ClassificationStoreError(ValueError):
    """Stable, non-sensitive store rejection reason."""


def classification_path(state_root: Path) -> Path:
    return Path(state_root) / "runtime" / "context" / "classifications.json"


def classification_backup_path(state_root: Path) -> Path:
    return classification_path(state_root).with_suffix(".json.bak")


def case_ref(scope_id: str, case_key: str) -> str:
    """Return an opaque stable case id from trusted scope plus caller case key."""
    if not str(scope_id).strip() or not str(case_key).strip():
        raise ClassificationStoreError("case_identity_invalid")
    digest = hashlib.sha256(f"{scope_id}\0{case_key}".encode("utf-8")).hexdigest()[:24]
    return f"case_{digest}"


def _empty(scope_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scope_id": scope_id,
        "revision": 0,
        "active_snapshot": None,
        "tombstones": {},
    }


def load_classifications(state_root: Path, scope_id: str) -> dict[str, Any]:
    path = classification_path(state_root)
    if not path.is_file():
        return _empty(scope_id)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ClassificationStoreError("store_corrupt") from None
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise ClassificationStoreError("store_version_unsupported")
    if value.get("scope_id") != scope_id:
        raise ClassificationStoreError("scope_mismatch")
    if type(value.get("revision")) is not int or value["revision"] < 0:
        raise ClassificationStoreError("store_corrupt")
    return value


@contextmanager
def _write_lock(state_root: Path) -> Iterator[None]:
    path = classification_path(state_root).with_name("classifications.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, payload: dict[str, Any], *, preserve_backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        if preserve_backup and path.is_file():
            try:
                previous = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = None
            if isinstance(previous, dict) and previous.get("schema_version") == SCHEMA_VERSION:
                backup = path.with_suffix(path.suffix + ".bak")
                backup_fd, backup_name = tempfile.mkstemp(
                    prefix=f".{backup.name}.", suffix=".tmp", dir=path.parent
                )
                backup_tmp = Path(backup_name)
                try:
                    with os.fdopen(backup_fd, "w", encoding="utf-8") as backup_fh:
                        json.dump(previous, backup_fh, ensure_ascii=False, indent=2, sort_keys=True)
                        backup_fh.write("\n")
                        backup_fh.flush()
                        os.fsync(backup_fh.fileno())
                    os.replace(backup_tmp, backup)
                except BaseException:
                    backup_tmp.unlink(missing_ok=True)
                    raise
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def recover_classifications(state_root: Path, scope_id: str) -> dict[str, Any]:
    """Explicitly restore the last valid snapshot backup after active-file damage.

    Recovery never happens silently: callers must opt in after observing
    ``store_corrupt``. The restored snapshot may be stale and retains its old
    revision so downstream consumers can diagnose and refresh it.
    """
    state_root = Path(state_root)
    backup = classification_backup_path(state_root)
    with _write_lock(state_root):
        if not backup.is_file():
            raise ClassificationStoreError("backup_missing")
        try:
            value = json.loads(backup.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise ClassificationStoreError("backup_corrupt") from None
        if (not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION
                or value.get("scope_id") != scope_id
                or type(value.get("revision")) is not int or value["revision"] < 0):
            raise ClassificationStoreError("backup_corrupt")
        _atomic_write(classification_path(state_root), value, preserve_backup=False)
        return deepcopy(value)


def _unique_strings(value: object, reason: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise ClassificationStoreError(reason)
    return list(dict.fromkeys(value))


def _prior_cases(current: dict[str, Any]) -> dict[str, dict[str, Any]]:
    snapshot = current.get("active_snapshot")
    rows = snapshot.get("cases", []) if isinstance(snapshot, dict) else []
    return {str(row.get("case_ref")): row for row in rows if isinstance(row, dict) and row.get("case_ref")}


def _normalize_cases(scope_id: str, cases: Iterable[dict[str, Any]], current: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    prior = _prior_cases(current)
    normalized: list[dict[str, Any]] = []
    key_to_ref: dict[str, str] = {}
    seen: set[str] = set()
    for raw in cases:
        if not isinstance(raw, dict):
            raise ClassificationStoreError("case_invalid")
        key = str(raw.get("case_key") or "").strip()
        ref = str(raw.get("case_ref") or case_ref(scope_id, key))
        if not key or ref != case_ref(scope_id, key) or ref in seen:
            raise ClassificationStoreError("case_identity_invalid")
        row = {
            "case_ref": ref,
            "case_key": key,
            "mail_refs": _unique_strings(raw.get("mail_refs"), "mail_refs_invalid"),
            "evidence_refs": _unique_strings(raw.get("evidence_refs"), "evidence_refs_invalid"),
        }
        for field in ("subject", "project_ref", "reason"):
            if raw.get(field) is not None:
                row[field] = str(raw[field])
        confirmation = raw.get("human_confirmation")
        if confirmation is None and ref in prior:
            confirmation = prior[ref].get("human_confirmation")
        if confirmation is not None:
            if not isinstance(confirmation, dict) or not confirmation.get("actor_ref"):
                raise ClassificationStoreError("human_confirmation_invalid")
            row["human_confirmation"] = deepcopy(confirmation)
        normalized.append(row)
        key_to_ref[key] = ref
        seen.add(ref)
    return normalized, key_to_ref


def _normalize_classifications(
    rows: Iterable[dict[str, Any]], key_to_ref: dict[str, str], known_refs: set[str],
    *, pack_fingerprint: str, classifier_version: str, source_revision: int, observed_at: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise ClassificationStoreError("classification_invalid")
        ref = str(raw.get("case_ref") or key_to_ref.get(str(raw.get("case_key") or "")) or "")
        status = str(raw.get("status") or "unknown")
        if ref not in known_refs or ref in seen or status not in _ALLOWED_STATUS:
            raise ClassificationStoreError("classification_invalid")
        row = {
            "case_ref": ref,
            "status": status,
            "primary_event_type": raw.get("primary_event_type"),
            "tags": deepcopy(raw.get("tags") or {}),
            "axes": deepcopy(raw.get("axes") or {}),
            "evidence_basis": str(raw.get("evidence_basis") or "insufficient"),
            "matched_rules": _unique_strings(raw.get("matched_rules"), "matched_rules_invalid"),
            "reason": str(raw.get("reason") or ""),
            "pack_fingerprint": pack_fingerprint,
            "classifier_version": classifier_version,
            "source_revision": source_revision,
            "observed_at": observed_at,
        }
        if not isinstance(row["tags"], dict) or not isinstance(row["axes"], dict):
            raise ClassificationStoreError("classification_invalid")
        normalized.append(row)
        seen.add(ref)
    return normalized


def _project_ledger_lifecycle(
    state_root: Path, case_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project the ledger's current lifecycle state onto case rows (derived only).

    Reuses ``case_ref`` for identity; reads the append-only ledger and never
    rewrites or deletes a ledger line.  A closed case stays closed here, so the
    classification projection does not resurrect it.
    """
    from . import case_ledger
    try:
        view = case_ledger.current_view(state_root)
    except Exception:
        return list(case_rows)
    attribute = case_ledger.DEFAULT_ATTRIBUTE
    projected: list[dict[str, Any]] = []
    for row in case_rows:
        record = view.get((row.get("case_ref"), attribute))
        if record is not None:
            row = dict(row)
            row["lifecycle"] = {
                "state": record.get("value"),
                "attribute": attribute,
                "source": record.get("source"),
            }
        projected.append(row)
    return projected


def publish_classifications(
    state_root: Path,
    *,
    scope_id: str,
    cases: Iterable[dict[str, Any]],
    classifications: Iterable[dict[str, Any]],
    coverage: dict[str, Any],
    pack_fingerprint: str,
    classifier_version: str,
    source_revision: int,
    observed_at: str | None = None,
    expected_revision: int | None = None,
    source_digest: str | None = None,
) -> dict[str, Any]:
    """Build a complete replacement snapshot, then atomically make it active."""
    if not scope_id or not pack_fingerprint or not classifier_version:
        raise ClassificationStoreError("snapshot_identity_invalid")
    if type(source_revision) is not int or source_revision < 0 or not isinstance(coverage, dict):
        raise ClassificationStoreError("snapshot_invalid")
    observed_at = observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = classification_path(state_root)
    with _write_lock(state_root):
        current = load_classifications(state_root, scope_id)
        if expected_revision is not None and expected_revision != current["revision"]:
            raise ClassificationStoreError("revision_conflict")
        active = current.get("active_snapshot")
        if isinstance(active, dict) and active.get("source_revision") == source_revision:
            prior_digest = active.get("source_digest")
            if source_digest is not None and prior_digest is not None and source_digest != prior_digest:
                raise ClassificationStoreError("source_revision_conflict")
        case_rows, key_to_ref = _normalize_cases(scope_id, cases, current)
        tombstones = dict(current.get("tombstones") or {})
        case_rows = [row for row in case_rows if row["case_ref"] not in tombstones]
        case_rows = _project_ledger_lifecycle(state_root, case_rows)
        known_refs = {row["case_ref"] for row in case_rows}
        class_rows = _normalize_classifications(
            classifications, key_to_ref, known_refs,
            pack_fingerprint=pack_fingerprint,
            classifier_version=classifier_version,
            source_revision=source_revision,
            observed_at=observed_at,
        )
        # A repeated analysis of the same immutable source and rule version is a read,
        # not a fresh observation.  Preserve revision, observed_at and human overlays.
        if (source_digest is not None and isinstance(active, dict)
                and active.get("source_digest") == source_digest
                and active.get("pack_fingerprint") == pack_fingerprint
                and active.get("classifier_version") == classifier_version):
            return deepcopy(current)
        revision = current["revision"] + 1
        snapshot_seed = f"{scope_id}|{revision}|{pack_fingerprint}|{classifier_version}|{source_revision}"
        snapshot = {
            "snapshot_id": hashlib.sha256(snapshot_seed.encode("utf-8")).hexdigest()[:24],
            "revision": revision,
            "pack_fingerprint": pack_fingerprint,
            "classifier_version": classifier_version,
            "source_revision": source_revision,
            "observed_at": observed_at,
            "coverage": deepcopy(coverage),
            "cases": case_rows,
            "classifications": class_rows,
        }
        if source_digest is not None:
            snapshot["source_digest"] = source_digest
        result = {
            "schema_version": SCHEMA_VERSION,
            "scope_id": scope_id,
            "revision": revision,
            "active_snapshot": snapshot,
            "tombstones": tombstones,
        }
        _atomic_write(path, result)
        return deepcopy(result)


def tombstone_cases(
    state_root: Path, *, scope_id: str, case_refs: Iterable[str], expected_revision: int | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    refs = list(dict.fromkeys(str(ref) for ref in case_refs if str(ref)))
    observed_at = observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _write_lock(state_root):
        current = load_classifications(state_root, scope_id)
        if expected_revision is not None and expected_revision != current["revision"]:
            raise ClassificationStoreError("revision_conflict")
        result = deepcopy(current)
        result["revision"] += 1
        tombstones = result.setdefault("tombstones", {})
        for ref in refs:
            tombstones[ref] = {"observed_at": observed_at, "revision": result["revision"]}
        active = result.get("active_snapshot")
        if isinstance(active, dict):
            active["cases"] = [row for row in active.get("cases", []) if row.get("case_ref") not in tombstones]
            active["classifications"] = [row for row in active.get("classifications", []) if row.get("case_ref") not in tombstones]
            active["revision"] = result["revision"]
        _atomic_write(classification_path(state_root), result)
        return deepcopy(result)


def lookup_case(state_root: Path, scope_id: str, ref: str) -> dict[str, Any]:
    current = load_classifications(state_root, scope_id)
    if ref in (current.get("tombstones") or {}):
        return {"case_ref": ref, "status": "tombstoned", "covered": False}
    active = current.get("active_snapshot")
    if not isinstance(active, dict):
        return {"case_ref": ref, "status": "unknown", "covered": False}
    cases = {row.get("case_ref"): row for row in active.get("cases", []) if isinstance(row, dict)}
    classes = {row.get("case_ref"): row for row in active.get("classifications", []) if isinstance(row, dict)}
    if ref not in cases:
        return {"case_ref": ref, "status": "unknown", "covered": False}
    return {**deepcopy(cases[ref]), **deepcopy(classes.get(ref, {"status": "unknown"})), "covered": True,
            "snapshot_revision": active.get("revision")}


def classification_lineage(state_root: Path) -> dict[str, Any] | None:
    """Return bounded snapshot provenance for projections without exposing cases."""
    path = classification_path(state_root)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    active = raw.get("active_snapshot") if isinstance(raw, dict) else None
    if not isinstance(active, dict):
        return None
    return {
        "scope_id": raw.get("scope_id"),
        "revision": raw.get("revision"),
        "snapshot_id": active.get("snapshot_id"),
        "pack_fingerprint": active.get("pack_fingerprint"),
        "classifier_version": active.get("classifier_version"),
        "source_revision": active.get("source_revision"),
        "observed_at": active.get("observed_at"),
        "coverage": deepcopy(active.get("coverage") or {}),
    }
