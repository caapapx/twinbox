"""Optional, local-only WeKnora capability adapter.

This module implements the *provider port* in Spec 014, not an assumed
WeKnora REST client.  It is intentionally useful with a fake provider in local
TDD only: production has no provider factory until ADR-004 and the live
capability gates are accepted.

The local state contains opaque source identities, hashes and bounded status
codes only.  It never persists email excerpts, MIME, attachments, model output
or provider response bodies.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Iterator, Mapping, Protocol, Sequence
from uuid import uuid4

from .evidence_contract import MAX_PAYLOAD_BYTES, SourceGrant

SCHEMA_VERSION = "1.0"
MAX_EXCERPT_CHARS = 512
MAX_JOURNAL_ENTRIES = 200


class WeKnoraSyncError(ValueError):
    """A stable, non-sensitive rejection or local-state reason."""


class WeKnoraProvider(Protocol):
    """The verified capability port; deliberately not a REST API declaration."""

    def lookup_by_source_key(self, scope: str, stable_key: str) -> Mapping[str, object]: ...

    def create_excerpt(
        self,
        scope: str,
        stable_key: str,
        payload: Mapping[str, object],
        attempt_id: str,
    ) -> Mapping[str, object]: ...

    def update_excerpt(
        self,
        scope: str,
        knowledge_ref: str,
        expected_hash: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def get_parse_status(self, scope: str, knowledge_ref: str) -> Mapping[str, object]: ...

    def search(
        self,
        scope: str,
        query: str,
        authorized_filter: Mapping[str, object],
        classification_filter: Mapping[str, object] | None,
        limit: int,
        deadline: float,
    ) -> Mapping[str, object]: ...

    def delete_excerpt(self, scope: str, knowledge_ref: str) -> Mapping[str, object]: ...


def sync_state_path(state_root: Path) -> Path:
    """Return the account-local state path; it is never a remote KB path."""
    return Path(state_root) / "runtime" / "context" / "weknora-sync.json"


def _empty_state() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "mappings": {}, "journal": []}


def load_sync_state(state_root: Path) -> dict[str, Any]:
    """Load an owned state snapshot, rejecting malformed state fail-closed."""
    path = sync_state_path(state_root)
    if not path.is_file():
        return _empty_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise WeKnoraSyncError("sync_state_corrupt") from None
    if (not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION
            or not isinstance(state.get("mappings"), dict)
            or not isinstance(state.get("journal"), list)):
        raise WeKnoraSyncError("sync_state_unsupported")
    return deepcopy(state)


@contextmanager
def _sync_lock(state_root: Path) -> Iterator[None]:
    path = sync_state_path(state_root).with_name("weknora-sync.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(raw_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, sort_keys=True, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _save_state(state_root: Path, state: Mapping[str, object]) -> None:
    _atomic_write(sync_state_path(state_root), state)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sync_diagnostics(state_root: Path) -> dict[str, Any]:
    """Return bounded local sync counters without exposing source content."""
    try:
        state = load_sync_state(state_root)
    except WeKnoraSyncError as exc:
        return {"available": False, "error": str(exc)}
    counts: dict[str, int] = {}
    mappings = state["mappings"]
    assert isinstance(mappings, dict)
    for value in mappings.values():
        if not isinstance(value, dict):
            continue
        name = value.get("sync_state")
        if isinstance(name, str) and len(name) <= 32:
            counts[name] = counts.get(name, 0) + 1
    return {
        "available": True,
        "mapping_count": len(mappings),
        "states": dict(sorted(counts.items())),
        "journal_entries": len(state["journal"]),
    }


def _bounded_text(value: object, *, limit: int, reason: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise WeKnoraSyncError(reason)
    return value[:limit]


def _mapping_id(scope_id: str, mail_ref: str) -> str:
    digest = hashlib.sha256(f"{scope_id}\0{mail_ref}".encode("utf-8")).hexdigest()[:32]
    return f"map_{digest}"


def _stable_title_key(scope_id: str, account_ref: str, mail_ref: str) -> str:
    """Produce a stable opaque key that does not contain subject or semantics."""
    digest = hashlib.sha256(f"{scope_id}\0{account_ref}\0{mail_ref}".encode("utf-8")).hexdigest()
    return f"tbx_{digest[:40]}"


def _payload_hash(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _source_identity(grant: SourceGrant, source: object) -> tuple[str, str, str]:
    if not grant.enabled:
        raise WeKnoraSyncError("source_disabled")
    if not grant.scope_id or not grant.account_ref:
        raise WeKnoraSyncError("source_binding_invalid")
    if not isinstance(source, dict):
        raise WeKnoraSyncError("source_invalid")

    scope_id = source.get("scope_id")
    if not isinstance(scope_id, str) or not scope_id.strip():
        raise WeKnoraSyncError("source_scope_invalid")
    if scope_id != grant.scope_id:
        raise WeKnoraSyncError("scope_mismatch")

    account_ref = source.get("account_ref")
    if not isinstance(account_ref, str) or account_ref != grant.account_ref:
        raise WeKnoraSyncError("source_binding_invalid")

    mail_ref = source.get("mail_ref")
    if not isinstance(mail_ref, str) or not mail_ref.strip():
        raise WeKnoraSyncError("source_identity_invalid")
    if mail_ref not in grant.mail_refs:
        raise WeKnoraSyncError("reference_forbidden")
    return scope_id, account_ref, mail_ref


def build_sync_payload(grant: SourceGrant, source: object) -> dict[str, Any]:
    """Build the strict, bounded outbound payload from trusted source content.

    ``original_excerpt`` is intentionally the only field eligible to become an
    external excerpt.  Existing classification/LLM projection fields are not
    copied, even when they are included by a caller.
    """
    scope_id, account_ref, mail_ref = _source_identity(grant, source)
    assert isinstance(source, dict)  # narrowed by _source_identity
    excerpt = _bounded_text(source.get("original_excerpt"), limit=MAX_EXCERPT_CHARS,
                            reason="original_excerpt_invalid")
    metadata = {
        "subject": _bounded_text(source.get("subject"), limit=256, reason="subject_invalid"),
        "sender": _bounded_text(source.get("sender"), limit=254, reason="sender_invalid"),
        "date": _bounded_text(source.get("date"), limit=64, reason="date_invalid"),
        "folder": _bounded_text(source.get("folder"), limit=256, reason="folder_invalid"),
        "thread_key": _bounded_text(source.get("thread_key"), limit=256, reason="thread_key_invalid"),
        "has_excerpt": bool(excerpt),
    }
    payload: dict[str, Any] = {
        "channel": "twinbox",
        "source": {"scope_id": scope_id, "mail_ref": mail_ref},
        "stable_title_key": _stable_title_key(scope_id, account_ref, mail_ref),
        "metadata": metadata,
        "excerpt": excerpt or None,
    }
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise WeKnoraSyncError("payload_invalid") from None
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise WeKnoraSyncError("payload_too_large")
    return payload


def _journal(
    state: dict[str, Any],
    *,
    scope_id: str,
    mail_ref: str,
    attempt_id: str,
    operation: str,
    state_name: str,
    error_code: str | None = None,
) -> None:
    row: dict[str, Any] = {
        "at": _now(),
        "scope_id": scope_id,
        "mail_ref": mail_ref,
        "attempt_id": attempt_id,
        "operation": operation,
        "state": state_name,
    }
    if error_code:
        row["error_code"] = error_code
    rows = state["journal"]
    assert isinstance(rows, list)
    rows.append(row)
    if len(rows) > MAX_JOURNAL_ENTRIES:
        del rows[:-MAX_JOURNAL_ENTRIES]


def _entry(
    *,
    scope_id: str,
    account_ref: str,
    mail_ref: str,
    thread_key: str,
    stable_title_key: str,
    writer_id: str,
) -> dict[str, Any]:
    return {
        "scope_id": scope_id,
        "account_ref": account_ref,
        "mail_ref": mail_ref,
        "thread_key": thread_key,
        "writer_id": writer_id,
        "visibility": "visible",
        "knowledge_ref": None,
        "stable_title_key": stable_title_key,
        "excerpt_hash": None,
        "pending_hash": None,
        "payload_revision": 0,
        "sync_state": "prepared",
        "parse_state": "unknown",
        "attempt_id": None,
        "pending_operation": None,
        "last_error_code": None,
        "updated_at": _now(),
    }


def _mark_attempt(
    state: dict[str, Any],
    entry: dict[str, Any],
    *,
    payload_hash: str,
    operation: str,
) -> str:
    attempt_id = f"attempt_{uuid4().hex}"
    entry.update({
        "pending_hash": payload_hash,
        "sync_state": "lookup" if operation == "create" else "uploading",
        "attempt_id": attempt_id,
        "pending_operation": operation,
        "last_error_code": None,
        "updated_at": _now(),
    })
    _journal(state, scope_id=entry["scope_id"], mail_ref=entry["mail_ref"], attempt_id=attempt_id,
             operation=operation, state_name="prepared")
    return attempt_id


def _provider_status(result: object, *, allowed: set[str]) -> tuple[str, Mapping[str, object]]:
    if not isinstance(result, Mapping):
        raise WeKnoraSyncError("provider_response_invalid")
    status = result.get("status")
    if not isinstance(status, str) or status not in allowed:
        raise WeKnoraSyncError("provider_response_invalid")
    return status, result


def _knowledge_ref(result: Mapping[str, object]) -> str:
    value = result.get("knowledge_ref")
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise WeKnoraSyncError("provider_response_invalid")
    return value


def _parse_state(result: Mapping[str, object]) -> str:
    value = result.get("parse_state", "pending")
    if not isinstance(value, str) or value not in {"pending", "ready", "failed", "unknown"}:
        return "unknown"
    return value


def _finish_success(
    state: dict[str, Any],
    entry: dict[str, Any],
    *,
    payload_hash: str,
    knowledge_ref: str,
    parse_state: str,
    operation: str,
) -> None:
    entry.update({
        "knowledge_ref": knowledge_ref,
        "excerpt_hash": payload_hash,
        "pending_hash": None,
        "payload_revision": int(entry.get("payload_revision") or 0) + 1,
        "sync_state": "parsing" if parse_state == "pending" else "searchable" if parse_state == "ready" else "failed",
        "parse_state": parse_state,
        "pending_operation": None,
        "last_error_code": None,
        "updated_at": _now(),
    })
    _journal(state, scope_id=entry["scope_id"], mail_ref=entry["mail_ref"],
             attempt_id=str(entry["attempt_id"] or ""), operation=operation, state_name="uploaded")


def _mark_uncertain(state: dict[str, Any], entry: dict[str, Any], *, operation: str) -> None:
    entry.update({"sync_state": "uncertain", "last_error_code": "provider_timeout", "updated_at": _now()})
    _journal(state, scope_id=entry["scope_id"], mail_ref=entry["mail_ref"],
             attempt_id=str(entry["attempt_id"] or ""), operation=operation,
             state_name="uncertain", error_code="provider_timeout")


def _mark_quarantined(state: dict[str, Any], entry: dict[str, Any], *, error_code: str) -> None:
    entry.update({"sync_state": "quarantined", "last_error_code": error_code, "updated_at": _now()})
    _journal(state, scope_id=entry["scope_id"], mail_ref=entry["mail_ref"],
             attempt_id=str(entry["attempt_id"] or ""),
             operation=str(entry.get("pending_operation") or "create"),
             state_name="quarantined", error_code=error_code)


def _reconcile_uncertain(
    state: dict[str, Any],
    entry: dict[str, Any],
    provider: WeKnoraProvider,
    *,
    payload_hash: str,
) -> dict[str, Any] | None:
    """Reconcile one uncertain write; return None only if a fresh create is safe."""
    operation = str(entry.get("pending_operation") or "create")
    try:
        status, result = _provider_status(
            provider.lookup_by_source_key(entry["scope_id"], entry["stable_title_key"]),
            allowed={"missing", "found", "conflict"},
        )
    except TimeoutError:
        entry.update({"last_error_code": "provider_timeout", "updated_at": _now()})
        _journal(state, scope_id=entry["scope_id"], mail_ref=entry["mail_ref"],
                 attempt_id=str(entry["attempt_id"] or ""), operation=operation,
                 state_name="uncertain", error_code="provider_timeout")
        return {"status": "uncertain"}
    except WeKnoraSyncError:
        _mark_quarantined(state, entry, error_code="provider_response_invalid")
        return {"status": "quarantined", "error": "provider_response_invalid"}

    if status == "conflict":
        _mark_quarantined(state, entry, error_code="source_key_conflict")
        return {"status": "quarantined", "error": "source_key_conflict"}
    if status == "missing":
        if operation == "create":
            return None
        # A timed-out update cannot be safely replayed when the old document has
        # disappeared: it could have been replaced by an unrelated writer.
        _mark_quarantined(state, entry, error_code="update_reconcile_missing")
        return {"status": "quarantined", "error": "update_reconcile_missing"}

    knowledge_ref = _knowledge_ref(result)
    if operation == "update":
        remote_hash = result.get("excerpt_hash")
        if not isinstance(remote_hash, str) or remote_hash != payload_hash:
            _mark_quarantined(state, entry, error_code="update_reconcile_unverified")
            return {"status": "quarantined", "error": "update_reconcile_unverified"}
    _finish_success(state, entry, payload_hash=payload_hash, knowledge_ref=knowledge_ref,
                    parse_state=_parse_state(result), operation=operation)
    return {"status": "reconciled", "knowledge_ref": knowledge_ref, "parse_state": entry["parse_state"]}


def _resolve_writer_id(state_root: Path, supplied: str | None) -> str:
    """Return a stable local-writer identity without introducing a remote lease."""
    if supplied is None:
        digest = hashlib.sha256(str(state_root.resolve()).encode("utf-8")).hexdigest()[:24]
        return f"local_{digest}"
    if (not isinstance(supplied, str) or not supplied.strip() or len(supplied) > 128
            or any(ord(char) < 32 for char in supplied)):
        raise WeKnoraSyncError("writer_id_invalid")
    return supplied


def sync_excerpt(
    state_root: Path,
    provider: WeKnoraProvider,
    grant: SourceGrant,
    source: object,
    *,
    writer_id: str | None = None,
) -> dict[str, Any]:
    """Synchronize one permitted excerpt through a single-writer provider port.

    The write intent is stored before a remote create/update.  A create timeout
    becomes ``uncertain``; a later attempt must look up the stable source key
    before another create.  This is local serialized idempotency, not a claim
    of distributed exactly-once behavior.
    """
    root = Path(state_root)
    writer = _resolve_writer_id(root, writer_id)
    payload = build_sync_payload(grant, source)
    scope_id = payload["source"]["scope_id"]
    mail_ref = payload["source"]["mail_ref"]
    assert isinstance(scope_id, str) and isinstance(mail_ref, str)
    payload_hash = _payload_hash(payload)
    map_id = _mapping_id(scope_id, mail_ref)
    account_ref = grant.account_ref
    thread_key = str(payload["metadata"]["thread_key"])

    with _sync_lock(root):
        state = load_sync_state(root)
        mappings = state["mappings"]
        assert isinstance(mappings, dict)
        entry = mappings.get(map_id)
        if not isinstance(entry, dict):
            entry = _entry(
                scope_id=scope_id, account_ref=account_ref, mail_ref=mail_ref,
                thread_key=thread_key, stable_title_key=payload["stable_title_key"], writer_id=writer,
            )
            mappings[map_id] = entry
        elif entry.get("scope_id") != scope_id or entry.get("mail_ref") != mail_ref:
            raise WeKnoraSyncError("mapping_identity_conflict")
        elif entry.get("account_ref") not in (None, account_ref):
            raise WeKnoraSyncError("mapping_identity_conflict")
        elif entry.get("writer_id") not in (None, writer):
            raise WeKnoraSyncError("writer_conflict")
        elif entry.get("visibility", "visible") != "visible":
            raise WeKnoraSyncError("source_revoked")
        else:
            # Early local-mock state had no account/thread/writer fields.  Fill
            # only approved locators; never backfill source excerpts.
            entry["account_ref"] = account_ref
            entry["thread_key"] = thread_key
            entry["writer_id"] = writer
            entry.setdefault("visibility", "visible")

        if entry.get("sync_state") == "uncertain":
            reconciled = _reconcile_uncertain(state, entry, provider, payload_hash=payload_hash)
            _save_state(state_root, state)
            if reconciled is not None:
                return reconciled
            # A missing lookup establishes that the original create did not
            # leave a record; continue with a fresh create attempt below.

        knowledge_ref = entry.get("knowledge_ref")
        current_hash = entry.get("excerpt_hash")
        if isinstance(knowledge_ref, str) and knowledge_ref and current_hash == payload_hash:
            return {"status": "skipped", "knowledge_ref": knowledge_ref, "parse_state": entry.get("parse_state", "unknown")}

        if isinstance(knowledge_ref, str) and knowledge_ref:
            operation = "update"
            attempt_id = _mark_attempt(state, entry, payload_hash=payload_hash, operation=operation)
            _save_state(state_root, state)
            try:
                status, result = _provider_status(
                    provider.update_excerpt(scope_id, knowledge_ref, str(current_hash or ""), payload),
                    allowed={"accepted", "conflict", "failed"},
                )
            except TimeoutError:
                _mark_uncertain(state, entry, operation=operation)
                _save_state(state_root, state)
                return {"status": "uncertain"}
            except WeKnoraSyncError:
                _mark_quarantined(state, entry, error_code="provider_response_invalid")
                _save_state(state_root, state)
                return {"status": "quarantined", "error": "provider_response_invalid"}
            if status == "conflict":
                _mark_quarantined(state, entry, error_code="update_conflict")
                _save_state(state_root, state)
                return {"status": "quarantined", "error": "update_conflict"}
            if status == "failed":
                entry.update({"sync_state": "retryable", "last_error_code": "provider_failed", "updated_at": _now()})
                _journal(state, scope_id=scope_id, mail_ref=mail_ref, attempt_id=attempt_id,
                         operation=operation, state_name="retryable", error_code="provider_failed")
                _save_state(state_root, state)
                return {"status": "retryable", "error": "provider_failed"}
            _finish_success(state, entry, payload_hash=payload_hash, knowledge_ref=knowledge_ref,
                            parse_state=_parse_state(result), operation=operation)
            _save_state(state_root, state)
            return {"status": "updated", "knowledge_ref": knowledge_ref, "parse_state": entry["parse_state"]}

        operation = "create"
        attempt_id = _mark_attempt(state, entry, payload_hash=payload_hash, operation=operation)
        _save_state(state_root, state)
        try:
            status, result = _provider_status(
                provider.lookup_by_source_key(scope_id, entry["stable_title_key"]),
                allowed={"missing", "found", "conflict"},
            )
        except TimeoutError:
            entry.update({"sync_state": "retryable", "last_error_code": "provider_timeout", "updated_at": _now()})
            _journal(state, scope_id=scope_id, mail_ref=mail_ref, attempt_id=attempt_id,
                     operation=operation, state_name="retryable", error_code="provider_timeout")
            _save_state(state_root, state)
            return {"status": "retryable", "error": "provider_timeout"}
        except WeKnoraSyncError:
            _mark_quarantined(state, entry, error_code="provider_response_invalid")
            _save_state(state_root, state)
            return {"status": "quarantined", "error": "provider_response_invalid"}

        if status == "conflict":
            _mark_quarantined(state, entry, error_code="source_key_conflict")
            _save_state(state_root, state)
            return {"status": "quarantined", "error": "source_key_conflict"}
        if status == "found":
            # State recovery must not assume the remote version matches our
            # outbound hash unless the verified provider explicitly says so.
            remote_hash = result.get("excerpt_hash")
            if not isinstance(remote_hash, str) or remote_hash != payload_hash:
                _mark_quarantined(state, entry, error_code="lookup_hash_unverified")
                _save_state(state_root, state)
                return {"status": "quarantined", "error": "lookup_hash_unverified"}
            ref = _knowledge_ref(result)
            _finish_success(state, entry, payload_hash=payload_hash, knowledge_ref=ref,
                            parse_state=_parse_state(result), operation=operation)
            _save_state(state_root, state)
            return {"status": "reconciled", "knowledge_ref": ref, "parse_state": entry["parse_state"]}

        entry.update({"sync_state": "uploading", "updated_at": _now()})
        _journal(state, scope_id=scope_id, mail_ref=mail_ref, attempt_id=attempt_id,
                 operation=operation, state_name="uploading")
        _save_state(state_root, state)
        try:
            status, result = _provider_status(
                provider.create_excerpt(scope_id, entry["stable_title_key"], payload, attempt_id),
                allowed={"accepted", "uncertain", "failed"},
            )
        except TimeoutError:
            _mark_uncertain(state, entry, operation=operation)
            _save_state(state_root, state)
            return {"status": "uncertain"}
        except WeKnoraSyncError:
            _mark_quarantined(state, entry, error_code="provider_response_invalid")
            _save_state(state_root, state)
            return {"status": "quarantined", "error": "provider_response_invalid"}

        if status == "uncertain":
            _mark_uncertain(state, entry, operation=operation)
            _save_state(state_root, state)
            return {"status": "uncertain"}
        if status == "failed":
            entry.update({"sync_state": "retryable", "last_error_code": "provider_failed", "updated_at": _now()})
            _journal(state, scope_id=scope_id, mail_ref=mail_ref, attempt_id=attempt_id,
                     operation=operation, state_name="retryable", error_code="provider_failed")
            _save_state(state_root, state)
            return {"status": "retryable", "error": "provider_failed"}

        ref = _knowledge_ref(result)
        _finish_success(state, entry, payload_hash=payload_hash, knowledge_ref=ref,
                        parse_state=_parse_state(result), operation=operation)
        _save_state(state_root, state)
        return {"status": "created", "knowledge_ref": ref, "parse_state": entry["parse_state"]}


# Retrieval remains local-mock only until ADR-004 and the live capability gates
# are accepted.  These limits deliberately bound both provider calls and tool
# envelopes; they are not claims about a product API's limits.
MAX_SEARCH_QUERY_CHARS = 1024
MAX_SEARCH_LIMIT = 25
DEFAULT_SEARCH_LIMIT = 5
DEFAULT_SEARCH_TIMEOUT_SECONDS = 2.0
SearchFallback = Callable[[str, Path, SourceGrant], Sequence[Mapping[str, object]]]


def _validate_search_request(
    grant: SourceGrant,
    query: object,
    *,
    limit: int,
    timeout_seconds: float,
) -> str:
    if not grant.enabled:
        raise WeKnoraSyncError("source_disabled")
    if not isinstance(grant.scope_id, str) or not grant.scope_id.strip():
        raise WeKnoraSyncError("source_binding_invalid")
    if not isinstance(grant.account_ref, str) or not grant.account_ref.strip():
        raise WeKnoraSyncError("source_binding_invalid")
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_SEARCH_QUERY_CHARS:
        raise WeKnoraSyncError("search_query_invalid")
    if type(limit) is not int or not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise WeKnoraSyncError("search_limit_invalid")
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds)) or not 0 < float(timeout_seconds) <= 30):
        raise WeKnoraSyncError("search_timeout_invalid")
    return query.strip()


def _searchable_mappings(state_root: Path, grant: SourceGrant) -> list[dict[str, str]]:
    """Take a short-lived authorized mapping snapshot before contacting a provider.

    A mapping must bind the same scope *and* account, have completed parsing,
    and name a grant-authorized mail ref.  Legacy local mock rows without the
    account binding are excluded rather than guessed.  Duplicate remote IDs are
    also excluded: a caller cannot safely decide which local source owns one.
    """
    with _sync_lock(state_root):
        state = load_sync_state(state_root)
        values = state.get("mappings")
        if not isinstance(values, dict):
            raise WeKnoraSyncError("sync_state_unsupported")
        candidates: list[dict[str, str]] = []
        for raw in values.values():
            if not isinstance(raw, dict):
                continue
            knowledge_ref = raw.get("knowledge_ref")
            mail_ref = raw.get("mail_ref")
            if (
                raw.get("scope_id") != grant.scope_id
                or raw.get("account_ref") != grant.account_ref
                or raw.get("visibility", "visible") != "visible"
                or raw.get("sync_state") != "searchable"
                or raw.get("parse_state") != "ready"
                or not isinstance(knowledge_ref, str)
                or not knowledge_ref.strip()
                or len(knowledge_ref) > 512
                or not isinstance(mail_ref, str)
                or mail_ref not in grant.mail_refs
            ):
                continue
            thread_key = raw.get("thread_key")
            candidates.append({
                "knowledge_ref": knowledge_ref,
                "mail_ref": mail_ref,
                "thread_key": thread_key[:256] if isinstance(thread_key, str) else "",
            })

    by_knowledge: dict[str, list[dict[str, str]]] = {}
    for entry in candidates:
        by_knowledge.setdefault(entry["knowledge_ref"], []).append(entry)
    # One remote identity must resolve to exactly one locally authorized source.
    return sorted(
        (rows[0] for rows in by_knowledge.values() if len(rows) == 1),
        key=lambda row: (row["knowledge_ref"], row["mail_ref"]),
    )


def _normalize_filter_values(value: object) -> tuple[str, ...]:
    if isinstance(value, str) and value:
        return (value,)
    if isinstance(value, list) and value and all(isinstance(item, str) and item for item in value):
        return tuple(sorted(set(value)))
    raise WeKnoraSyncError("classification_filter_invalid")


def _normalize_classification_filter(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or not value:
        raise WeKnoraSyncError("classification_filter_invalid")
    allowed = {"status", "primary_event_type", "tags", "axes"}
    if any(not isinstance(key, str) or key not in allowed for key in value):
        raise WeKnoraSyncError("classification_filter_invalid")
    out: dict[str, object] = {}
    for key in ("status", "primary_event_type"):
        if key in value:
            item = value[key]
            if not isinstance(item, str) or not item:
                raise WeKnoraSyncError("classification_filter_invalid")
            out[key] = item
    for key in ("tags", "axes"):
        if key not in value:
            continue
        dimensions = value[key]
        if not isinstance(dimensions, Mapping) or not dimensions:
            raise WeKnoraSyncError("classification_filter_invalid")
        normalized: dict[str, tuple[str, ...]] = {}
        for name, wanted in dimensions.items():
            if not isinstance(name, str) or not name or len(name) > 96:
                raise WeKnoraSyncError("classification_filter_invalid")
            normalized[name] = _normalize_filter_values(wanted)
        out[key] = normalized
    if not out:
        raise WeKnoraSyncError("classification_filter_invalid")
    return out


def _classification_index(
    state_root: Path,
    scope_id: str,
) -> tuple[str, dict[str, list[dict[str, object]]]]:
    """Join the active 013 snapshot without treating it as an authorization grant."""
    try:
        from .classification_store import ClassificationStoreError, load_classifications

        stored = load_classifications(state_root, scope_id)
    except (ClassificationStoreError, OSError):
        return "unknown", {}
    active = stored.get("active_snapshot")
    if not isinstance(active, dict):
        return "unknown", {}
    coverage = active.get("coverage")
    coverage_state = coverage.get("state") if isinstance(coverage, dict) else None
    if coverage_state not in {"complete", "partial", "unknown", "stale"}:
        coverage_state = "unknown"

    classifications = {
        row.get("case_ref"): row
        for row in active.get("classifications", [])
        if isinstance(row, dict) and isinstance(row.get("case_ref"), str)
    }
    by_mail_ref: dict[str, list[dict[str, object]]] = {}
    for case in active.get("cases", []):
        if not isinstance(case, dict) or not isinstance(case.get("case_ref"), str):
            continue
        row = classifications.get(case["case_ref"], {})
        tags = row.get("tags") if isinstance(row, dict) else {}
        axes = row.get("axes") if isinstance(row, dict) else {}
        classification = {
            "case_ref": case["case_ref"],
            "status": row.get("status", "unknown") if isinstance(row, dict) else "unknown",
            "primary_event_type": row.get("primary_event_type") if isinstance(row, dict) else None,
            "tags": deepcopy(tags) if isinstance(tags, dict) else {},
            "axes": deepcopy(axes) if isinstance(axes, dict) else {},
        }
        refs = case.get("mail_refs")
        if not isinstance(refs, list):
            continue
        for mail_ref in refs:
            if isinstance(mail_ref, str) and mail_ref:
                by_mail_ref.setdefault(mail_ref, []).append(classification)
    return str(coverage_state), by_mail_ref


def _matches_dimension_filter(actual: object, wanted: tuple[str, ...]) -> bool:
    if isinstance(actual, str):
        values = {actual}
    elif isinstance(actual, list) and all(isinstance(item, str) for item in actual):
        values = set(actual)
    else:
        return False
    return set(wanted).issubset(values)


def _matches_classification(row: Mapping[str, object], filter_spec: Mapping[str, object]) -> bool:
    for key in ("status", "primary_event_type"):
        expected = filter_spec.get(key)
        if expected is not None and row.get(key) != expected:
            return False
    for key in ("tags", "axes"):
        required = filter_spec.get(key)
        if required is None:
            continue
        actual = row.get(key)
        if not isinstance(required, Mapping) or not isinstance(actual, Mapping):
            return False
        for name, wanted in required.items():
            if not isinstance(name, str) or not isinstance(wanted, tuple):
                return False
            if not _matches_dimension_filter(actual.get(name), wanted):
                return False
    return True


def _filter_mappings_by_classification(
    mappings: Sequence[dict[str, str]],
    classifications: Mapping[str, list[dict[str, object]]],
    filter_spec: Mapping[str, object] | None,
) -> list[dict[str, str]]:
    if filter_spec is None:
        return list(mappings)
    return [
        row for row in mappings
        if any(_matches_classification(classification, filter_spec)
               for classification in classifications.get(row["mail_ref"], []))
    ]


def _classification_projection(
    classifications: Mapping[str, list[dict[str, object]]],
    mail_ref: str,
    coverage_state: str,
) -> tuple[str, dict[str, list[str]]]:
    rows = classifications.get(mail_ref, [])
    case_refs = sorted({str(row["case_ref"]) for row in rows if isinstance(row.get("case_ref"), str)})
    types = sorted({str(row["primary_event_type"]) for row in rows
                    if isinstance(row.get("primary_event_type"), str) and row["primary_event_type"]})
    if rows:
        coverage = "covered"
    elif coverage_state == "partial":
        coverage = "partial"
    elif coverage_state in {"complete", "stale"}:
        coverage = "unclassified"
    else:
        coverage = "unknown"
    return coverage, {"case_refs": case_refs, "primary_event_types": types}


def _live_status_by_mail_ref(state_root: Path) -> dict[str, dict[str, object]]:
    """Return a bounded current-pulse projection; absence means unknown, not inactive."""
    try:
        from .pulse import load_activity_pulse

        pulse = load_activity_pulse(state_root)
    except (OSError, RuntimeError, ValueError):
        return {}
    generated_at = pulse.get("generated_at")
    observed_at = generated_at[:64] if isinstance(generated_at, str) else None
    rows = pulse.get("thread_index")
    if not isinstance(rows, list):
        return {}
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        mail_ref = row.get("latest_message_ref")
        if not isinstance(mail_ref, str) or not mail_ref:
            continue
        tags = row.get("queue_tags")
        safe_tags = sorted({tag for tag in tags if isinstance(tag, str) and len(tag) <= 96}) if isinstance(tags, list) else []
        item: dict[str, object] = {"queue_tags": safe_tags}
        if observed_at is not None:
            item["observed_at"] = observed_at
        last_activity = row.get("last_activity_at")
        if isinstance(last_activity, str) and len(last_activity) <= 64:
            item["last_activity_at"] = last_activity
        result[mail_ref] = item
    return result


def _search_response(result: object) -> tuple[str, str, list[Mapping[str, object]]]:
    if not isinstance(result, Mapping):
        raise WeKnoraSyncError("provider_response_invalid")
    status = result.get("status")
    coverage = result.get("coverage", "unknown")
    hits = result.get("hits")
    if status not in {"ok", "partial", "failed"} or coverage not in {"complete", "partial", "unknown"}:
        raise WeKnoraSyncError("provider_response_invalid")
    if not isinstance(hits, list) or any(not isinstance(hit, Mapping) for hit in hits):
        raise WeKnoraSyncError("provider_response_invalid")
    return str(status), str(coverage), hits


def _safe_score(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return value


def _render_hits(
    rows: Sequence[Mapping[str, object]],
    *,
    mappings_by_knowledge: Mapping[str, dict[str, str]],
    mappings_by_mail: Mapping[str, dict[str, str]],
    backend: str,
    classifications: Mapping[str, list[dict[str, object]]],
    classification_coverage: str,
    live_status: Mapping[str, dict[str, object]],
    limit: int,
) -> tuple[list[dict[str, object]], bool]:
    """Drop untrusted/oversized rows and construct the narrow SearchHit shape."""
    hits: list[dict[str, object]] = []
    filtered = False
    seen: set[str] = set()
    for raw in rows:
        if backend == "weknora":
            ref = raw.get("knowledge_ref")
            mapping = mappings_by_knowledge.get(ref) if isinstance(ref, str) else None
        else:
            mail_ref = raw.get("mail_ref")
            mapping = mappings_by_mail.get(mail_ref) if isinstance(mail_ref, str) else None
        if mapping is None:
            filtered = True
            continue
        knowledge_ref = mapping["knowledge_ref"]
        if knowledge_ref in seen:
            filtered = True
            continue
        excerpt = raw.get("excerpt")
        if excerpt is not None and (not isinstance(excerpt, str) or len(excerpt) > MAX_EXCERPT_CHARS):
            filtered = True
            continue
        score = _safe_score(raw.get("score"))
        if raw.get("score") is not None and score is None:
            filtered = True
            continue
        coverage, classification = _classification_projection(
            classifications, mapping["mail_ref"], classification_coverage,
        )
        hit: dict[str, object] = {
            "knowledge_ref": knowledge_ref,
            "mail_ref": mapping["mail_ref"],
            "thread_key": mapping["thread_key"],
            "excerpt": excerpt,
            "retrieval_backend": backend,
            "score": score,
            "score_origin": backend,
            "classification_coverage": coverage,
            "classification": classification,
            "live_status": deepcopy(live_status.get(mapping["mail_ref"])),
        }
        hits.append(hit)
        seen.add(knowledge_ref)
        if len(hits) >= limit:
            break
    return hits, filtered


def _default_fallback(
    query: str,
    state_root: Path,
    _grant: SourceGrant,
    *,
    mail_refs: frozenset[str],
    limit: int,
) -> Sequence[Mapping[str, object]]:
    from .select import search_authorized

    return search_authorized(query, state_root, mail_refs=mail_refs, limit=limit)


def _fallback_result(
    fallback: Callable[..., Sequence[Mapping[str, object]]],
    *,
    query: str,
    state_root: Path,
    grant: SourceGrant,
    mail_refs: frozenset[str],
    mappings_by_knowledge: Mapping[str, dict[str, str]],
    mappings_by_mail: Mapping[str, dict[str, str]],
    classifications: Mapping[str, list[dict[str, object]]],
    classification_coverage: str,
    live_status: Mapping[str, dict[str, object]],
    limit: int,
    diagnostic: str,
) -> dict[str, object]:
    try:
        rows = fallback(query, state_root, grant, mail_refs=mail_refs, limit=limit)
    except Exception:
        return {
            "status": "partial",
            "hits": [],
            "coverage": {"remote": "unknown", "classification": classification_coverage},
            "diagnostics": [diagnostic, "sidecar_failed"],
        }
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return {
            "status": "partial",
            "hits": [],
            "coverage": {"remote": "unknown", "classification": classification_coverage},
            "diagnostics": [diagnostic, "sidecar_response_invalid"],
        }
    safe_rows = [row for row in rows if isinstance(row, Mapping)]
    hits, filtered = _render_hits(
        safe_rows,
        mappings_by_knowledge=mappings_by_knowledge,
        mappings_by_mail=mappings_by_mail,
        backend="sidecar",
        classifications=classifications,
        classification_coverage=classification_coverage,
        live_status=live_status,
        limit=limit,
    )
    diagnostics = [diagnostic]
    if filtered or len(safe_rows) != len(rows):
        diagnostics.append("sidecar_hits_filtered")
    return {
        "status": "fallback",
        "hits": hits,
        "coverage": {"remote": "unknown", "classification": classification_coverage},
        "diagnostics": diagnostics,
    }


def search_excerpts(
    state_root: Path,
    provider: WeKnoraProvider,
    grant: SourceGrant,
    query: object,
    *,
    classification_filter: object = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    timeout_seconds: float = DEFAULT_SEARCH_TIMEOUT_SECONDS,
    fallback: Callable[..., Sequence[Mapping[str, object]]] | None = None,
) -> dict[str, object]:
    """Search only exact grant-authorized mappings, with isolated sidecar fallback.

    The source grant is checked before any provider call.  Classification
    predicates are evaluated locally against the active 013 snapshot to produce
    an exact allowlist of remote knowledge IDs; they are never used as a
    post-hoc substitute for source authorization.  A provider timeout/failure
    chooses the sidecar as a separate backend rather than mixing incomparable
    raw scores.
    """
    text = _validate_search_request(grant, query, limit=limit, timeout_seconds=timeout_seconds)
    filter_spec = _normalize_classification_filter(classification_filter)
    mappings = _searchable_mappings(Path(state_root), grant)
    coverage_state, classifications = _classification_index(Path(state_root), grant.scope_id)

    if filter_spec is not None and coverage_state != "complete":
        return {
            "status": "partial",
            "hits": [],
            "coverage": {"remote": "unknown", "classification": coverage_state},
            "diagnostics": ["classification_unavailable"],
        }
    mappings = _filter_mappings_by_classification(mappings, classifications, filter_spec)
    if not mappings:
        return {
            "status": "no_authorized_sources",
            "hits": [],
            "coverage": {"remote": "unknown", "classification": coverage_state},
            "diagnostics": ["no_authorized_sources"],
        }

    mappings_by_knowledge = {row["knowledge_ref"]: row for row in mappings}
    mappings_by_mail = {row["mail_ref"]: row for row in mappings}
    mail_refs = frozenset(mappings_by_mail)
    authorized_filter: dict[str, object] = {
        "scope_id": grant.scope_id,
        "mail_refs": tuple(sorted(mail_refs)),
        "knowledge_refs": tuple(sorted(mappings_by_knowledge)),
    }
    live_status = _live_status_by_mail_ref(Path(state_root))
    selected_fallback = fallback or _default_fallback
    deadline = time.monotonic() + float(timeout_seconds)
    try:
        remote_status, remote_coverage, remote_rows = _search_response(
            provider.search(grant.scope_id, text, authorized_filter, None, limit, deadline)
        )
    except TimeoutError:
        return _fallback_result(
            selected_fallback, query=text, state_root=Path(state_root), grant=grant, mail_refs=mail_refs,
            mappings_by_knowledge=mappings_by_knowledge, mappings_by_mail=mappings_by_mail,
            classifications=classifications, classification_coverage=coverage_state,
            live_status=live_status, limit=limit, diagnostic="weknora_timeout",
        )
    except Exception:
        return _fallback_result(
            selected_fallback, query=text, state_root=Path(state_root), grant=grant, mail_refs=mail_refs,
            mappings_by_knowledge=mappings_by_knowledge, mappings_by_mail=mappings_by_mail,
            classifications=classifications, classification_coverage=coverage_state,
            live_status=live_status, limit=limit, diagnostic="weknora_unavailable",
        )

    if remote_status == "failed":
        return _fallback_result(
            selected_fallback, query=text, state_root=Path(state_root), grant=grant, mail_refs=mail_refs,
            mappings_by_knowledge=mappings_by_knowledge, mappings_by_mail=mappings_by_mail,
            classifications=classifications, classification_coverage=coverage_state,
            live_status=live_status, limit=limit, diagnostic="weknora_failed",
        )
    hits, filtered = _render_hits(
        remote_rows,
        mappings_by_knowledge=mappings_by_knowledge,
        mappings_by_mail=mappings_by_mail,
        backend="weknora",
        classifications=classifications,
        classification_coverage=coverage_state,
        live_status=live_status,
        limit=limit,
    )
    diagnostics = ["remote_hits_filtered"] if filtered else []
    status = "partial" if remote_status == "partial" or (filtered and not hits) else "ok"
    return {
        "status": status,
        "hits": hits,
        "coverage": {"remote": remote_coverage, "classification": coverage_state},
        "diagnostics": diagnostics,
    }


def _revoke_identity(grant: SourceGrant, mail_ref: object) -> tuple[str, str, str]:
    """Validate a trusted revocation locator.

    Revocation deliberately does not require ``grant.enabled``: once a source
    grant is turned off, the owner still needs a bounded way to hide and delete
    its already-created retrieval copy.  Callers must still supply the original
    trusted scope/account/mail binding; a payload cannot choose another one.
    """
    if not isinstance(grant.scope_id, str) or not grant.scope_id.strip():
        raise WeKnoraSyncError("source_binding_invalid")
    if not isinstance(grant.account_ref, str) or not grant.account_ref.strip():
        raise WeKnoraSyncError("source_binding_invalid")
    if not isinstance(mail_ref, str) or not mail_ref or mail_ref not in grant.mail_refs:
        raise WeKnoraSyncError("reference_forbidden")
    return grant.scope_id, grant.account_ref, mail_ref


def _delete_status(result: object) -> str:
    if not isinstance(result, Mapping):
        raise WeKnoraSyncError("provider_response_invalid")
    status = result.get("status")
    if status not in {"deleted", "absent", "pending", "failed"}:
        raise WeKnoraSyncError("provider_response_invalid")
    return str(status)


def revoke_excerpt(
    state_root: Path,
    provider: WeKnoraProvider,
    grant: SourceGrant,
    *,
    mail_ref: object,
) -> dict[str, str]:
    """Hide one mapped retrieval copy before attempting provider deletion.

    This is a local capability operation for the normal revoke/delete path, not
    an assertion that the provider has deleted bytes.  A timeout or failure
    keeps the local entry hidden and in ``delete_pending``; a later call may
    retry deletion, but no ordinary sync/search can make it visible again.
    """
    scope_id, account_ref, trusted_mail_ref = _revoke_identity(grant, mail_ref)
    root = Path(state_root)
    map_id = _mapping_id(scope_id, trusted_mail_ref)
    with _sync_lock(root):
        state = load_sync_state(root)
        mappings = state["mappings"]
        assert isinstance(mappings, dict)
        entry = mappings.get(map_id)
        if not isinstance(entry, dict):
            return {"status": "absent"}
        if (entry.get("scope_id") != scope_id or entry.get("account_ref") != account_ref
                or entry.get("mail_ref") != trusted_mail_ref):
            raise WeKnoraSyncError("mapping_identity_conflict")
        if entry.get("sync_state") == "deleted":
            entry["visibility"] = "hidden"
            _save_state(root, state)
            return {"status": "deleted"}
        knowledge_ref = entry.get("knowledge_ref")
        if not isinstance(knowledge_ref, str) or not knowledge_ref:
            entry.update({
                "visibility": "hidden", "sync_state": "deleted", "parse_state": "unknown",
                "pending_operation": None, "last_error_code": None, "updated_at": _now(),
            })
            _journal(state, scope_id=scope_id, mail_ref=trusted_mail_ref, attempt_id="",
                     operation="delete", state_name="deleted")
            _save_state(root, state)
            return {"status": "deleted"}

        attempt_id = f"attempt_{uuid4().hex}"
        entry.update({
            "visibility": "hidden", "sync_state": "delete_pending", "pending_operation": "delete",
            "attempt_id": attempt_id, "last_error_code": None, "updated_at": _now(),
        })
        _journal(state, scope_id=scope_id, mail_ref=trusted_mail_ref, attempt_id=attempt_id,
                 operation="delete", state_name="prepared")
        _save_state(root, state)
        try:
            status = _delete_status(provider.delete_excerpt(scope_id, knowledge_ref))
        except TimeoutError:
            status = "pending"
            error_code = "provider_timeout"
        except Exception:
            status = "failed"
            error_code = "provider_failed"
        else:
            error_code = "provider_failed" if status == "failed" else None

        if status in {"deleted", "absent"}:
            entry.update({
                "visibility": "hidden", "sync_state": "deleted", "parse_state": "unknown",
                "pending_operation": None, "pending_hash": None, "last_error_code": None, "updated_at": _now(),
            })
            _journal(state, scope_id=scope_id, mail_ref=trusted_mail_ref, attempt_id=attempt_id,
                     operation="delete", state_name="deleted")
            _save_state(root, state)
            return {"status": "deleted"}

        entry.update({
            "visibility": "hidden", "sync_state": "delete_pending", "last_error_code": error_code,
            "updated_at": _now(),
        })
        _journal(state, scope_id=scope_id, mail_ref=trusted_mail_ref, attempt_id=attempt_id,
                 operation="delete", state_name="delete_pending", error_code=error_code)
        _save_state(root, state)
        return {"status": "delete_pending", "error": error_code or "provider_pending"}
