"""Reference-only ingest envelopes for Agent OS (no full bodies)."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .pulse import load_activity_pulse

EXCERPT_LIMIT = 280
CURSOR_CACHE_MAX_FILES = 32


def _clip(text: object, limit: int = EXCERPT_LIMIT) -> str:
    raw = " ".join(str(text or "").split())
    if len(raw) <= limit:
        return raw
    return raw[: limit - 1] + "…"


def _stable_id(account_id: str, thread_key: str, message_ref: str = "") -> str:
    basis = f"{account_id}|{thread_key}|{message_ref}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def _load_context_envelopes(account_root: Path) -> list[dict[str, Any]]:
    path = account_root / "runtime" / "context" / "phase1-context.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    envelopes = data.get("envelopes") if isinstance(data, dict) else None
    if not isinstance(envelopes, list):
        return []
    return [e for e in envelopes if isinstance(e, dict)]


def _cursor_error(code: str) -> dict[str, Any]:
    return {"ok": False, "error": code, "recovery": "restart_without_cursor"}


def _cursor_token(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    checksum = hashlib.sha256(raw).hexdigest()[:16]
    return f"tbx1.{body}.{checksum}"


def _parse_cursor(token: str) -> dict[str, Any]:
    if token.startswith("tbx") and not token.startswith("tbx1."):
        raise ValueError("unsupported_cursor_version")
    if not token.startswith("tbx1."):
        raise ValueError("legacy_cursor")
    try:
        _, body, checksum = token.split(".", 2)
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        if hashlib.sha256(raw).hexdigest()[:16] != checksum:
            raise ValueError
        value = json.loads(raw)
    except Exception:
        raise ValueError("cursor_invalid") from None
    if not isinstance(value, dict) or value.get("v") != 1:
        raise ValueError("unsupported_cursor_version")
    return value


def _cursor_cache_path(account_root: Path, snapshot_id: str) -> Path:
    return account_root / "runtime" / "context" / "ingest-cursors" / f"{snapshot_id}.json"


def _prune_cursor_cache(directory: Path, *, now: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    survivors: list[tuple[float, Path]] = []
    for candidate in directory.glob("*.json"):
        try:
            cached = json.loads(candidate.read_text(encoding="utf-8"))
            expires_at = cached.get("expires_at") if isinstance(cached, dict) else None
            if type(expires_at) is not int or expires_at < now:
                candidate.unlink(missing_ok=True)
                continue
            survivors.append((candidate.stat().st_mtime, candidate))
        except (OSError, json.JSONDecodeError):
            candidate.unlink(missing_ok=True)
    # Leave one slot for the snapshot about to be written. Snapshot IDs are
    # content-addressed, so pruning affects only resumability after the TTL.
    for _, candidate in sorted(survivors)[: max(0, len(survivors) - CURSOR_CACHE_MAX_FILES + 1)]:
        candidate.unlink(missing_ok=True)


def _write_cursor_cache(path: Path, value: dict[str, Any]) -> None:
    _prune_cursor_cache(path.parent, now=int(time.time()))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _classification_by_mail(account_root: Path, account_id: str) -> dict[str, dict[str, Any]]:
    try:
        from .classification_store import load_classifications
        stored = load_classifications(account_root, account_id)
    except Exception:
        return {}
    active = stored.get("active_snapshot")
    if not isinstance(active, dict):
        return {}
    classes = {row.get("case_ref"): row for row in active.get("classifications", []) if isinstance(row, dict)}
    out: dict[str, dict[str, Any]] = {}
    for case in active.get("cases", []):
        if not isinstance(case, dict):
            continue
        ref = case.get("case_ref")
        classification = classes.get(ref, {"status": "unknown"})
        projection = {
            "case_ref": ref,
            "semantics": {k: classification.get(k) for k in (
                "status", "primary_event_type", "tags", "axes", "evidence_basis",
                "pack_fingerprint", "classifier_version", "source_revision", "observed_at",
            ) if classification.get(k) is not None},
        }
        for mail_ref in case.get("mail_refs", []):
            if isinstance(mail_ref, str):
                out[mail_ref] = projection
    return out


def _build_current_ingest_rows(account_root: Path, account_id: str) -> list[dict[str, Any]]:
    try:
        pulse = load_activity_pulse(account_root)
    except Exception:
        pulse = {}
    threads = pulse.get("thread_index") if isinstance(pulse, dict) else None
    source_rows = ([t for t in threads if isinstance(t, dict)]
                   if isinstance(threads, list) and threads else _load_context_envelopes(account_root))
    classified = _classification_by_mail(account_root, account_id)
    items: list[dict[str, Any]] = []
    for row in source_rows:
        thread_key = str(row.get("thread_key") or row.get("subject") or "")
        message_ref = str(row.get("latest_message_ref") or row.get("message_id") or row.get("id") or "")
        generated = str(row.get("last_activity_at") or row.get("date") or row.get("generated_at") or "")
        ref_id = _stable_id(account_id, thread_key, message_ref)
        excerpt = _clip(row.get("why") or row.get("action_hint") or row.get("latest_subject") or row.get("subject") or "")
        metadata = {
            "subject": row.get("latest_subject") or row.get("subject"),
            "from_addr": row.get("from_addr") or row.get("from") or row.get("sender"),
            "date": generated or None, "excerpt": excerpt,
            "recipient_role": row.get("recipient_role"),
            "queue_tags": row.get("queue_tags") if isinstance(row.get("queue_tags"), list) else [],
        }
        metadata = {k: v for k, v in metadata.items() if v not in (None, "", [])}
        envelope = {
            "id": ref_id, "schema_version": "1.0", "source_account": account_id,
            "reference": {"account_id": account_id, "thread_key": thread_key,
                          "message_ref": message_ref or None,
                          "folder": row.get("folder") or row.get("mailbox") or "INBOX"},
            "metadata": metadata,
            "attributes": row.get("attributes") if isinstance(row.get("attributes"), dict) else {},
        }
        projection = classified.get(message_ref)
        if projection:
            envelope.update(projection)
        for banned in ("body", "html", "text", "raw", "attachment", "attachments", "mime"):
            envelope.pop(banned, None)
            envelope["metadata"].pop(banned, None)
        items.append(envelope)
    return items


def build_ingest_envelopes(
    account_root: Path,
    *,
    account_id: str = "default",
    since_cursor: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Build reference-only pages with a scope-bound, frozen high-watermark cursor."""
    limit = max(1, min(int(limit or 50), 200))
    token = (since_cursor or "").strip()
    now = int(time.time())
    offset = 0
    snapshot_id = ""
    expires_at = now + 900
    items: list[dict[str, Any]]

    if token:
        try:
            cursor = _parse_cursor(token)
        except ValueError as exc:
            if str(exc) == "legacy_cursor":
                # Compatibility for the pre-v1 opaque id/ISO cursor. New pages always
                # return tbx1 tokens; legacy reads remain best-effort and stateless.
                current = _build_current_ingest_rows(account_root, account_id)
                items = [row for row in current if row["id"] > token]
                page = items[:limit]
                return {"ok": True, "schema_version": "1.0", "account_id": account_id,
                        "count": len(page), "cursor": {"since": token, "next": None}, "envelopes": page}
            return _cursor_error(str(exc))
        if cursor.get("scope") != account_id:
            return _cursor_error("cursor_scope_mismatch")
        if cursor.get("filter") != "all":
            return _cursor_error("cursor_filter_mismatch")
        if type(cursor.get("exp")) is not int or cursor["exp"] < now:
            return _cursor_error("cursor_expired")
        if type(cursor.get("offset")) is not int or cursor["offset"] < 0:
            return _cursor_error("cursor_invalid")
        snapshot_id = str(cursor.get("snapshot") or "")
        cache_path = _cursor_cache_path(account_root, snapshot_id)
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _cursor_error("cursor_expired")
        if cache.get("scope") != account_id or cache.get("expires_at", 0) < now:
            return _cursor_error("cursor_expired")
        items = cache.get("envelopes") if isinstance(cache.get("envelopes"), list) else []
        offset = cursor["offset"]
        expires_at = cursor["exp"]
    else:
        items = _build_current_ingest_rows(account_root, account_id)
        canonical = json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        snapshot_id = hashlib.sha256(f"{account_id}|{canonical}".encode("utf-8")).hexdigest()[:24]
        _write_cursor_cache(_cursor_cache_path(account_root, snapshot_id), {
            "schema_version": "1.0", "scope": account_id, "snapshot": snapshot_id,
            "expires_at": expires_at, "envelopes": items,
        })

    page = items[offset: offset + limit]
    next_offset = offset + len(page)
    next_token = None
    # Preserve the pre-v1 contract for a fresh read: even when its first page
    # exhausts the snapshot, return one terminal checkpoint that replays as an
    # empty page.  Continuation pages still end with ``next=None``.
    if next_offset < len(items) or not token:
        next_token = _cursor_token({"v": 1, "scope": account_id, "snapshot": snapshot_id,
                                    "offset": next_offset, "filter": "all", "exp": expires_at})
    return {
        "ok": True, "schema_version": "1.0", "account_id": account_id, "count": len(page),
        "cursor": {"since": token or None, "next": next_token, "snapshot": snapshot_id,
                   "expires_at": expires_at},
        "envelopes": page,
    }


def load_event_records(
    account_root: Path,
    *,
    account_id: str = "default",
    limit: int = 50,
) -> dict[str, Any]:
    path = account_root / "runtime" / "validation" / "phase-4" / "events.json"
    events: list[dict[str, Any]] = []
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            raw = data.get("events") if isinstance(data, dict) else data
            if isinstance(raw, list):
                for ev in raw:
                    if not isinstance(ev, dict):
                        continue
                    item = dict(ev)
                    item["source_account"] = account_id
                    for banned in ("body", "html", "text", "raw", "attachment", "attachments"):
                        item.pop(banned, None)
                    fields = item.get("fields")
                    if isinstance(fields, dict):
                        item["fields"] = {k: v for k, v in fields.items() if v not in (None, "", [])}
                    events.append(item)
        except (json.JSONDecodeError, OSError):
            events = []
    events = events[: max(1, min(int(limit or 50), 200))]
    return {"ok": True, "account_id": account_id, "count": len(events), "events": events}
