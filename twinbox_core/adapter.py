"""Reference-only ingest envelopes for Agent OS (no full bodies)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .pulse import load_activity_pulse

EXCERPT_LIMIT = 280


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


def build_ingest_envelopes(
    account_root: Path,
    *,
    account_id: str = "default",
    since_cursor: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Build reference + bounded excerpt envelopes; never include body/html/attachments."""
    limit = max(1, min(int(limit or 50), 200))
    cursor_baseline = (since_cursor or "").strip()

    try:
        pulse = load_activity_pulse(account_root)
    except Exception:
        pulse = {}

    threads = pulse.get("thread_index") if isinstance(pulse, dict) else None
    source_rows: list[dict[str, Any]]
    if isinstance(threads, list) and threads:
        source_rows = [t for t in threads if isinstance(t, dict)]
    else:
        source_rows = _load_context_envelopes(account_root)

    items: list[dict[str, Any]] = []
    next_cursor = cursor_baseline
    for row in source_rows:
        thread_key = str(row.get("thread_key") or row.get("subject") or "")
        message_ref = str(row.get("latest_message_ref") or row.get("message_id") or row.get("id") or "")
        generated = str(row.get("last_activity_at") or row.get("date") or row.get("generated_at") or "")
        ref_id = _stable_id(account_id, thread_key, message_ref)
        if cursor_baseline:
            # Cursor is opaque: accept either prior envelope id or ISO timestamp.
            if ref_id <= cursor_baseline:
                continue
            if generated and generated <= cursor_baseline and len(cursor_baseline) >= 10 and cursor_baseline[4] == "-":
                continue
        excerpt = _clip(row.get("why") or row.get("action_hint") or row.get("latest_subject") or row.get("subject") or "")
        envelope = {
            "id": ref_id,
            "source_account": account_id,
            "reference": {
                "account_id": account_id,
                "thread_key": thread_key,
                "message_ref": message_ref or None,
                "folder": row.get("folder") or row.get("mailbox") or "INBOX",
            },
            "metadata": {
                "subject": row.get("latest_subject") or row.get("subject"),
                "from_addr": row.get("from_addr") or row.get("from") or row.get("sender"),
                "date": generated or None,
                "excerpt": excerpt,
                "recipient_role": row.get("recipient_role"),
                "queue_tags": row.get("queue_tags") if isinstance(row.get("queue_tags"), list) else [],
            },
            "attributes": row.get("attributes") if isinstance(row.get("attributes"), dict) else {},
        }
        for banned in ("body", "html", "text", "raw", "attachment", "attachments", "mime"):
            envelope.pop(banned, None)
            envelope["metadata"].pop(banned, None)
        items.append(envelope)
        if ref_id > next_cursor:
            next_cursor = ref_id
        if len(items) >= limit:
            break

    return {
        "ok": True,
        "account_id": account_id,
        "count": len(items),
        "cursor": {"since": cursor_baseline or None, "next": next_cursor or None},
        "envelopes": items,
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
                    events.append(item)
        except (json.JSONDecodeError, OSError):
            events = []
    events = events[: max(1, min(int(limit or 50), 200))]
    return {"ok": True, "account_id": account_id, "count": len(events), "events": events}
