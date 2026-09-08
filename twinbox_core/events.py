"""Evidence-backed event records from pack classification (no full body)."""

from __future__ import annotations

import hashlib
from typing import Any
from pathlib import Path

from .imap_fetch import _write_json
from .pack import load_active_pack
from .pulse import normalize_thread_key
from .rules import hard_match, semantic_band


def _event_id(event_type: str, ref: str) -> str:
    return hashlib.sha256(f"{event_type}|{ref}".encode("utf-8")).hexdigest()[:16]


def extract_events(context: dict[str, Any], state_root: Path) -> list[dict[str, Any]]:
    pack = load_active_pack(state_root)
    envelopes = [e for e in context.get("envelopes", []) if isinstance(e, dict)]
    events: list[dict[str, Any]] = []
    types = []
    if pack:
        classification = pack.get("classification") or {}
        types = classification.get("event_types") or []
    if not isinstance(types, list) or not types:
        types = [{"id": "unclassified"}]
    for env in envelopes:
        ref = f"{env.get('folder', 'INBOX')}#{env.get('id', '')}"
        matched = None
        for spec in types:
            if not isinstance(spec, dict):
                continue
            cond = spec.get("when") or spec
            if hard_match(cond, env) or semantic_band(pack, env, state_root) == "hit":
                matched = spec
                break
        etype = str((matched or {}).get("id") or "unclassified")
        events.append({
            "id": _event_id(etype, ref),
            "type": etype,
            "thread_key": normalize_thread_key(env.get("subject")),
            "mail_ref": {"folder": env.get("folder"), "uid": env.get("id"), "message_id": env.get("message_id")},
            "fields": {
                "subject": env.get("subject"),
                "from_addr": env.get("from_addr"),
                "recipient_role": env.get("recipient_role"),
            },
        })
    out = state_root / "runtime" / "validation" / "phase-4" / "events.json"
    _write_json(out, {"events": events})
    return events
