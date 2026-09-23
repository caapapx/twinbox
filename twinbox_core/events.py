"""Evidence-backed event records from pack classification (no full body)."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from pathlib import Path

from .imap_fetch import _write_json
from .pack import load_active_pack
from .pulse import normalize_thread_key
from .rules import event_semantic_band, hard_match


def _event_id(event_type: str, ref: str) -> str:
    return hashlib.sha256(f"{event_type}|{ref}".encode("utf-8")).hexdigest()[:16]



def classify_envelope(pack: dict[str, Any] | None, env: dict[str, Any], state_root: Path) -> dict[str, Any]:
    """A deterministic mail-level projection; not an ACL or a business-case identity."""
    types = ((pack or {}).get("classification") or {}).get("event_types") or []
    matches = []
    for spec in types:
        if not isinstance(spec, dict):
            continue
        cond = spec.get("when", spec)
        hard = hard_match(cond, env)
        if hard or event_semantic_band(cond, env, state_root) == "hit":
            matches.append({"id": spec["id"], "priority": spec.get("priority", 0),
                            "basis": "explicit" if hard else "inferred",
                            "tags": spec.get("tags", {}), "axes": spec.get("axes", {})})
    matches.sort(key=lambda m: (-m["priority"], m["id"]))
    leaders = [m for m in matches if m["priority"] == matches[0]["priority"]] if matches else []
    winner = leaders[0] if len(leaders) == 1 else None
    return {
        "classification_status": "classified" if winner else ("needs_confirmation" if leaders else "unknown"),
        "classification_candidates": matches,
        "semantics": {
            "primary_event_type": winner["id"] if winner else None,
            "tags": winner["tags"] if winner else {},
            "axes": winner["axes"] if winner else {},
            "evidence_basis": winner["basis"] if winner else "insufficient",
            "pack": {k: (pack or {}).get(k) for k in ("id", "version", "fingerprint")},
        },
    }

def extract_events(context: dict[str, Any], state_root: Path) -> list[dict[str, Any]]:
    pack = load_active_pack(state_root)
    envelopes = [e for e in context.get("envelopes", []) if isinstance(e, dict)]
    events: list[dict[str, Any]] = []
    for env in envelopes:
        ref = f"{env.get('folder', 'INBOX')}#{env.get('id', '')}"
        classification = classify_envelope(pack, env, state_root)
        etype = classification["semantics"]["primary_event_type"] or "unclassified"
        events.append({
            **classification,
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

    # Publish the long-lived classification projection separately from the short
    # briefing artifacts.  A mail locator is only the default case seam; callers
    # may use classification_store directly for one-mail/many-case models.
    from .classification_store import publish_classifications
    scope_id = str(context.get("source_account") or state_root.name or "local")
    source_material = [{
        "folder": env.get("folder", "INBOX"), "id": str(env.get("id", "")),
        "message_id": env.get("message_id"), "subject": env.get("subject"),
        "date": env.get("date"),
    } for env in envelopes]
    source_digest = hashlib.sha256(
        json.dumps(source_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    source_revision = int(source_digest[:12], 16)
    cases = []
    classifications = []
    for event in events:
        ref = f"{event['mail_ref'].get('folder') or 'INBOX'}#{event['mail_ref'].get('uid') or ''}"
        cases.append({
            "case_key": ref, "subject": event.get("fields", {}).get("subject"),
            "mail_refs": [ref], "evidence_refs": [ref],
        })
        semantics = event.get("semantics") or {}
        classifications.append({
            "case_key": ref, "status": event.get("classification_status", "unknown"),
            "primary_event_type": semantics.get("primary_event_type"),
            "tags": semantics.get("tags") or {}, "axes": semantics.get("axes") or {},
            "evidence_basis": semantics.get("evidence_basis") or "insufficient",
            "matched_rules": [row.get("id") for row in event.get("classification_candidates", []) if row.get("id")],
        })
    publish_classifications(
        state_root, scope_id=scope_id, cases=cases, classifications=classifications,
        coverage={
            "window": {"since": context.get("since"), "until": context.get("until")},
            "enumerated": len(envelopes), "analyzed": len(events), "failed": 0,
        },
        pack_fingerprint=str((pack or {}).get("fingerprint") or "none"),
        classifier_version="013.1", source_revision=source_revision,
        observed_at=str(context.get("generated_at") or context.get("fetch_at") or "") or None,
        source_digest=source_digest,
    )
    return events
