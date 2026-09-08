"""Envelope and thread recipient_role (archive context_builder semantics)."""

from __future__ import annotations

from email.utils import getaddresses
from typing import Any

ROLES = ("direct", "cc_only", "group_only", "indirect", "unknown")
MESSAGE_ROLES = ("to", "cc", "group", "unknown")


def _addr_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        parts = [str(v) for v in value if str(v).strip()]
        blob = ", ".join(parts)
    else:
        blob = str(value or "")
    if not blob.strip():
        return []
    return [addr.lower().strip() for _, addr in getaddresses([blob]) if addr]


def parse_envelope_recipient_role(
    *,
    owner_addr: str,
    to: object = "",
    cc: object = "",
    list_id: object = "",
) -> str:
    """Message-level role: to / cc / group / unknown."""
    owner = str(owner_addr or "").lower().strip()
    if not owner:
        return "unknown"
    to_addrs = _addr_list(to)
    cc_addrs = _addr_list(cc)
    list_header = str(list_id or "").strip()
    if owner in to_addrs:
        return "to"
    if owner in cc_addrs:
        return "cc"
    if list_header or to_addrs or cc_addrs:
        return "group"
    return "unknown"


def aggregate_thread_recipient_role(rows: list[dict[str, Any]]) -> str:
    """Collapse message-level roles: any to → direct."""
    classified = {
        str(row.get("recipient_role", "") or "")
        for row in rows
        if str(row.get("recipient_role", "") or "") in {"to", "cc", "group"}
    }
    if "to" in classified:
        return "direct"
    if classified == {"cc"}:
        return "cc_only"
    if classified == {"group"}:
        return "group_only"
    if classified == {"cc", "group"}:
        return "indirect"
    return "unknown"


def apply_envelope_role(env: dict[str, Any], owner_addr: str) -> dict[str, Any]:
    env = dict(env)
    env["recipient_role"] = parse_envelope_recipient_role(
        owner_addr=owner_addr,
        to=env.get("to", ""),
        cc=env.get("cc", ""),
        list_id=env.get("list_id", ""),
    )
    return env
