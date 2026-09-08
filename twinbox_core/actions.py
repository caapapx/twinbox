"""Dry-run action proposals + local review + jsonl audit (no SMTP)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .imap_fetch import _write_json
from .pack import load_active_pack
from .pulse import load_activity_pulse, normalize_thread_key

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _audit_path(state_root: Path) -> Path:
    return state_root / "runtime" / "audit" / "actions.jsonl"


def _proposals_path(state_root: Path) -> Path:
    return state_root / "runtime" / "actions" / "proposals.json"


def _append_audit(state_root: Path, record: dict[str, Any]) -> None:
    path = _audit_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = dict(record)
    record.setdefault("at", datetime.now(SHANGHAI).isoformat(timespec="seconds"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_proposals(state_root: Path) -> list[dict[str, Any]]:
    data = json.loads(_proposals_path(state_root).read_text(encoding="utf-8")) if _proposals_path(state_root).is_file() else {}
    rows = data.get("proposals", []) if isinstance(data, dict) else []
    return [r for r in rows if isinstance(r, dict)]


def _idempotency_key(policy_id: str, thread_key: str) -> str:
    return f"{policy_id}:{normalize_thread_key(thread_key)}"


def scan_proposals(state_root: Path) -> dict[str, Any]:
    pack = load_active_pack(state_root)
    policies = (pack or {}).get("action_policy") or []
    if not isinstance(policies, list):
        policies = []
    existing = {str(p.get("idempotency_key")): p for p in _load_proposals(state_root)}
    try:
        pulse = load_activity_pulse(state_root)
    except RuntimeError:
        pulse = {"needs_attention": []}
    attention = [t for t in pulse.get("needs_attention", []) if isinstance(t, dict)]
    created: list[dict[str, Any]] = []
    for policy in policies:
        if not isinstance(policy, dict) or not policy.get("id"):
            continue
        if not policy.get("enabled", True):
            continue
        action_type = str(policy.get("action_type") or "notify")
        target_scope = policy.get("target_scope") or []
        for item in attention:
            if policy.get("require_projection") and item.get("projection") != policy.get("require_projection"):
                continue
            tk = normalize_thread_key(item.get("thread_key", ""))
            key = _idempotency_key(str(policy["id"]), tk)
            if key in existing:
                continue
            targets = list(target_scope) if isinstance(target_scope, list) else [target_scope]
            status = "proposed"
            if len(targets) != 1:
                status = "needs_human"
                targets = []
            proposal = {
                "proposal_id": key,
                "idempotency_key": key,
                "policy_id": policy["id"],
                "policy_version": str((pack or {}).get("version") or ""),
                "action_type": action_type,
                "target_scope": targets,
                "thread_key": tk,
                "evidence_refs": [item.get("latest_message_ref")],
                "status": status,
                "card_payload": {
                    "title": f"Twinbox 提案：{action_type}",
                    "thread_key": tk,
                    "why": item.get("why", ""),
                    "excerpt": str(item.get("why", ""))[:120],
                    "actions": ["confirm", "reject"],
                },
            }
            existing[key] = proposal
            created.append(proposal)
            _append_audit(state_root, {"event": "propose", **proposal})
    all_rows = list(existing.values())
    _write_json(_proposals_path(state_root), {"proposals": all_rows})
    return {"ok": True, "proposals": all_rows, "created": len(created)}


def review_proposal(state_root: Path, proposal_id: str, action: str, reason: str = "") -> dict[str, Any]:
    rows = _load_proposals(state_root)
    found = None
    for row in rows:
        if str(row.get("proposal_id")) == proposal_id or str(row.get("idempotency_key")) == proposal_id:
            found = row
            break
    if found is None:
        return {"ok": False, "error": "proposal not found"}
    if action not in {"confirm", "reject", "expire"}:
        return {"ok": False, "error": "action must be confirm|reject|expire"}
    status = {"confirm": "confirmed", "reject": "rejected", "expire": "expired"}[action]
    found["status"] = status
    found["review_reason"] = reason
    _write_json(_proposals_path(state_root), {"proposals": rows})
    _append_audit(state_root, {"event": "review", "proposal_id": proposal_id, "status": status, "reason": reason})
    return {"ok": True, "proposal": found}
