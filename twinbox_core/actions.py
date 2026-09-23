"""Policy-governed local action proposals and HITL confirmations (no SMTP)."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .imap_fetch import _write_json
from .pack import load_active_pack
from .pulse import load_activity_pulse, normalize_thread_key

SHANGHAI = ZoneInfo("Asia/Shanghai")
CONFIRMATION_TOKEN_TTL_SECONDS = 5 * 60
_AWAITING_CONFIRMATION = "awaiting_confirmation"
_TERMINAL_STATUSES = frozenset({"confirmed", "rejected", "expired"})


def _audit_path(state_root: Path) -> Path:
    return state_root / "runtime" / "audit" / "actions.jsonl"


def _proposals_path(state_root: Path) -> Path:
    return state_root / "runtime" / "actions" / "proposals.json"


def _as_shanghai(now: datetime | None = None) -> datetime:
    value = now or datetime.now(SHANGHAI)
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _iso(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


def _append_audit(state_root: Path, record: dict[str, Any], *, now: datetime | None = None) -> None:
    """Append an audit record without ever persisting a raw confirmation token."""
    path = _audit_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = dict(record)
    record.pop("confirmation_token", None)
    record.setdefault("at", _iso(_as_shanghai(now)))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _load_proposals(state_root: Path) -> list[dict[str, Any]]:
    path = _proposals_path(state_root)
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    rows = data.get("proposals", []) if isinstance(data, dict) else []
    return [r for r in rows if isinstance(r, dict)]


def _save_proposals(state_root: Path, rows: list[dict[str, Any]]) -> None:
    _write_json(_proposals_path(state_root), {"proposals": rows})


def _idempotency_key(policy_id: str, thread_key: str) -> str:
    return f"{policy_id}:{normalize_thread_key(thread_key)}"


def _bounded_text(value: object, *, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


def _draft_payload(
    *,
    proposal_id: str,
    idempotency_key: str,
    policy_id: str,
    policy_version: str,
    action_type: str,
    target_scope: list[Any],
    thread_key: str,
    evidence_refs: list[Any],
    why: object,
) -> dict[str, Any]:
    """Canonical, bounded business payload that a human is actually confirming."""
    return {
        "schema_version": "twinbox.action-draft.v1",
        "proposal_id": proposal_id,
        "idempotency_key": idempotency_key,
        "policy": {"id": policy_id, "version": policy_version},
        "action": {"type": action_type, "target_scope": list(target_scope)},
        "thread_key": thread_key,
        "evidence_refs": [str(ref) for ref in evidence_refs if ref],
        "summary": {"why": _bounded_text(why)},
    }


def _payload_hash(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _card_payload(proposal: dict[str, Any]) -> dict[str, Any]:
    draft = proposal["draft_payload"]
    return {
        "title": f"Twinbox 提案：{proposal['action_type']}",
        "thread_key": proposal["thread_key"],
        "why": draft["summary"]["why"],
        "excerpt": draft["summary"]["why"],
        "actions": ["confirm", "reject"],
        # The card contains an auditable, bounded decision object, not a mail body.
        "draft_payload": draft,
    }


def _new_draft(
    *,
    policy: dict[str, Any],
    pack: dict[str, Any] | None,
    item: dict[str, Any],
) -> dict[str, Any]:
    thread_key = normalize_thread_key(item.get("thread_key", ""))
    policy_id = str(policy["id"])
    idempotency_key = _idempotency_key(policy_id, thread_key)
    declared_targets = policy.get("target_scope") or []
    targets = list(declared_targets) if isinstance(declared_targets, list) else [declared_targets]
    status = "draft"
    if len(targets) != 1:
        # No best-effort target selection. A person must resolve the ambiguity.
        status = "needs_human"
        targets = []
    proposal = {
        "proposal_id": idempotency_key,
        "idempotency_key": idempotency_key,
        "policy_id": policy_id,
        "policy_version": str((pack or {}).get("version") or ""),
        "action_type": str(policy.get("action_type") or "notify"),
        "target_scope": targets,
        "thread_key": thread_key,
        "evidence_refs": [item.get("latest_message_ref")],
        "status": status,
    }
    proposal["draft_payload"] = _draft_payload(
        proposal_id=proposal["proposal_id"],
        idempotency_key=proposal["idempotency_key"],
        policy_id=proposal["policy_id"],
        policy_version=proposal["policy_version"],
        action_type=proposal["action_type"],
        target_scope=proposal["target_scope"],
        thread_key=proposal["thread_key"],
        evidence_refs=proposal["evidence_refs"],
        why=item.get("why", ""),
    )
    proposal["draft_payload_hash"] = _payload_hash(proposal["draft_payload"])
    proposal["card_payload"] = _card_payload(proposal)
    return proposal


def _clear_card_token(proposal: dict[str, Any]) -> None:
    card = proposal.get("card_payload")
    if not isinstance(card, dict):
        return
    confirmation = card.get("confirmation")
    if isinstance(confirmation, dict):
        confirmation.pop("token", None)


def _issue_confirmation(proposal: dict[str, Any], *, now: datetime) -> str:
    """Move a resolved draft into a short-lived human confirmation wait state."""
    token = f"ctk_{secrets.token_urlsafe(24)}"
    expires_at = now + timedelta(seconds=CONFIRMATION_TOKEN_TTL_SECONDS)
    proposal["status"] = _AWAITING_CONFIRMATION
    proposal["confirmation"] = {
        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "token_state": "issued",
        "issued_at": _iso(now),
        "expires_at": _iso(expires_at),
        "used_at": None,
    }
    card = proposal.setdefault("card_payload", _card_payload(proposal))
    card["confirmation"] = {
        "required": True,
        "token": token,
        "expires_at": _iso(expires_at),
    }
    # MCP clients can use this machine-readable contract to end the tool turn
    # and ask the human for a separate confirmation message.
    card["interaction"] = {
        "human_confirmation_required": True,
        "must_stop_agent_turn": True,
        "same_turn_confirmation_forbidden": True,
    }
    return token


def _expire_confirmation(proposal: dict[str, Any], *, reason: str, now: datetime) -> bool:
    """Expire only a pending confirmation; return whether state changed."""
    if proposal.get("status") != _AWAITING_CONFIRMATION:
        return False
    confirmation = proposal.get("confirmation")
    if not isinstance(confirmation, dict):
        return False
    proposal["status"] = "expired"
    confirmation["token_state"] = "expired"
    confirmation["expired_at"] = _iso(now)
    confirmation["expiry_reason"] = reason
    _clear_card_token(proposal)
    return True


def _expires_at(proposal: dict[str, Any]) -> datetime | None:
    confirmation = proposal.get("confirmation")
    if not isinstance(confirmation, dict) or not isinstance(confirmation.get("expires_at"), str):
        return None
    try:
        return _as_shanghai(datetime.fromisoformat(confirmation["expires_at"]))
    except ValueError:
        return None


def _expire_if_due(proposal: dict[str, Any], *, now: datetime) -> str | None:
    expires_at = _expires_at(proposal)
    if proposal.get("status") == _AWAITING_CONFIRMATION and (expires_at is None or now >= expires_at):
        return "confirmation_token_expired" if _expire_confirmation(
            proposal, reason="confirmation_token_expired", now=now
        ) else None
    return None


def _audit_proposal_event(
    state_root: Path,
    event: str,
    proposal: dict[str, Any],
    *,
    now: datetime,
    reason: str = "",
) -> None:
    _append_audit(
        state_root,
        {
            "event": event,
            "proposal_id": proposal.get("proposal_id"),
            "idempotency_key": proposal.get("idempotency_key"),
            "policy_id": proposal.get("policy_id"),
            "policy_version": proposal.get("policy_version"),
            "status": proposal.get("status"),
            "draft_payload_hash": proposal.get("draft_payload_hash"),
            "reason": reason,
        },
        now=now,
    )


def _current_by_idempotency(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("idempotency_key")): row for row in rows if row.get("idempotency_key")}


def scan_proposals(state_root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Create/reissue bounded dry-run drafts. This never contacts or writes a mailbox."""
    current_time = _as_shanghai(now)
    rows = _load_proposals(state_root)
    changed = False
    for row in rows:
        reason = _expire_if_due(row, now=current_time)
        if reason:
            changed = True
            _audit_proposal_event(state_root, "confirmation_expired", row, now=current_time, reason=reason)

    pack = load_active_pack(state_root)
    policies = (pack or {}).get("action_policy") or []
    if not isinstance(policies, list):
        policies = []
    existing = _current_by_idempotency(rows)
    try:
        pulse = load_activity_pulse(state_root)
    except RuntimeError:
        pulse = {"needs_attention": []}
    attention = [item for item in pulse.get("needs_attention", []) if isinstance(item, dict)]
    created: list[dict[str, Any]] = []

    for policy in policies:
        if not isinstance(policy, dict) or not policy.get("id") or not policy.get("enabled", True):
            continue
        for item in attention:
            if policy.get("require_projection") and item.get("projection") != policy.get("require_projection"):
                continue
            draft = _new_draft(policy=policy, pack=pack, item=item)
            key = draft["idempotency_key"]
            prior = existing.get(key)
            if prior is not None:
                # Idempotency covers the exact decision payload. A changed payload
                # invalidates a pending token and reissues a new draft in place.
                if prior.get("status") in _TERMINAL_STATUSES or prior.get("draft_payload_hash") == draft["draft_payload_hash"]:
                    continue
                if _expire_confirmation(prior, reason="draft_payload_changed", now=current_time):
                    _audit_proposal_event(
                        state_root, "confirmation_expired", prior, now=current_time, reason="draft_payload_changed"
                    )
                prior.clear()
                prior.update(draft)
                if prior["status"] == "draft":
                    _audit_proposal_event(state_root, "draft_refreshed", prior, now=current_time)
                    _issue_confirmation(prior, now=current_time)
                    _audit_proposal_event(state_root, "confirmation_issued", prior, now=current_time)
                else:
                    _audit_proposal_event(state_root, "draft_refreshed", prior, now=current_time, reason="target_ambiguity")
                changed = True
                continue

            rows.append(draft)
            existing[key] = draft
            created.append(draft)
            _audit_proposal_event(state_root, "draft_created", draft, now=current_time)
            if draft["status"] == "draft":
                _issue_confirmation(draft, now=current_time)
                _audit_proposal_event(state_root, "confirmation_issued", draft, now=current_time)
            else:
                _audit_proposal_event(state_root, "needs_human", draft, now=current_time, reason="target_ambiguity")
            changed = True

    if changed:
        _save_proposals(state_root, rows)
    return {"ok": True, "proposals": rows, "created": len(created)}


def _error(error: str, code: str) -> dict[str, Any]:
    return {"ok": False, "error": error, "code": code}


def review_proposal(
    state_root: Path,
    proposal_id: str,
    action: str,
    reason: str = "",
    *,
    confirmation_token: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Review a local dry-run proposal; confirmation never performs execution."""
    if action not in {"confirm", "reject", "expire"}:
        return _error("action must be confirm|reject|expire", "invalid_action")
    current_time = _as_shanghai(now)
    rows = _load_proposals(state_root)
    found = next(
        (
            row
            for row in rows
            if str(row.get("proposal_id")) == proposal_id or str(row.get("idempotency_key")) == proposal_id
        ),
        None,
    )
    if found is None:
        return _error("proposal not found", "proposal_not_found")

    expiry_reason = _expire_if_due(found, now=current_time)
    if expiry_reason:
        _save_proposals(state_root, rows)
        _audit_proposal_event(state_root, "confirmation_expired", found, now=current_time, reason=expiry_reason)
        return _error("confirmation token expired", "confirmation_token_expired")
    if found.get("status") in _TERMINAL_STATUSES:
        return _error("proposal is not awaiting confirmation", "invalid_proposal_state")

    if action == "confirm":
        if found.get("status") == "needs_human":
            return _error("proposal target requires human selection", "target_ambiguity")
        if found.get("status") != _AWAITING_CONFIRMATION:
            return _error("proposal is not awaiting confirmation", "invalid_proposal_state")
        actual_payload_hash = _payload_hash(found.get("draft_payload"))
        if not hmac.compare_digest(str(found.get("draft_payload_hash") or ""), actual_payload_hash):
            _expire_confirmation(found, reason="draft_payload_hash_mismatch", now=current_time)
            _save_proposals(state_root, rows)
            _audit_proposal_event(
                state_root, "confirmation_expired", found, now=current_time, reason="draft_payload_hash_mismatch"
            )
            return _error("draft payload no longer matches its confirmation token", "confirmation_payload_mismatch")
        if not confirmation_token:
            return _error("confirmation token required", "confirmation_token_required")
        confirmation = found.get("confirmation")
        token_hash = confirmation.get("token_hash") if isinstance(confirmation, dict) else ""
        supplied_hash = hashlib.sha256(confirmation_token.encode("utf-8")).hexdigest()
        if not isinstance(token_hash, str) or not hmac.compare_digest(token_hash, supplied_hash):
            _append_audit(
                state_root,
                {
                    "event": "confirmation_rejected",
                    "proposal_id": found.get("proposal_id"),
                    "idempotency_key": found.get("idempotency_key"),
                    "status": found.get("status"),
                    "reason": "confirmation_token_invalid",
                },
                now=current_time,
            )
            return _error("confirmation token is invalid", "confirmation_token_invalid")

        assert isinstance(confirmation, dict)  # narrowed after the token-hash check
        found["status"] = "confirmed"
        confirmation["token_state"] = "used"
        confirmation["used_at"] = _iso(current_time)
        _clear_card_token(found)
        # This increment deliberately has no transition into `executing`.
        found["execution"] = {
            "status": "blocked_read_only",
            "reason": "Twinbox confirmation does not authorize mailbox or outbound execution",
        }
        found["review_reason"] = reason
        _save_proposals(state_root, rows)
        _audit_proposal_event(state_root, "confirmation_confirmed", found, now=current_time, reason=reason)
        return {"ok": True, "proposal": found}

    if action == "reject":
        found["status"] = "rejected"
        found["review_reason"] = reason
        _clear_card_token(found)
        _save_proposals(state_root, rows)
        _audit_proposal_event(state_root, "confirmation_rejected", found, now=current_time, reason=reason)
        return {"ok": True, "proposal": found}

    # Explicit local expiry is safe from either a pending token or a target-ambiguity hold.
    if found.get("status") == _AWAITING_CONFIRMATION:
        _expire_confirmation(found, reason="manually_expired", now=current_time)
    else:
        found["status"] = "expired"
    found["review_reason"] = reason
    _save_proposals(state_root, rows)
    _audit_proposal_event(state_root, "confirmation_expired", found, now=current_time, reason="manually_expired")
    return {"ok": True, "proposal": found}
