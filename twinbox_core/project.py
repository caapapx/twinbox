"""User-facing attention projections: action_required / watch / reference."""

from __future__ import annotations

from typing import Any
from pathlib import Path

from .pack import load_active_pack


def _axes(item: dict[str, Any]) -> dict[str, str]:
    tags = item.get("queue_tags") or []
    urgency = "high" if "urgent" in tags else ("medium" if "pending" in tags else "low")
    actionability = "high" if "pending" in tags or item.get("action_hint") else "low"
    if "pending" not in tags and urgency == "high":
        actionability = "low"
    interest = "high" if item.get("recipient_role") in {"direct", "to"} else "medium"
    sensitivity = "flagged" if "sensitive" in str(item.get("why", "")).lower() else "normal"
    return {
        "urgency": urgency,
        "actionability": actionability,
        "interest": interest,
        "sensitivity": sensitivity,
    }


def project_item(item: dict[str, Any], pack: dict[str, Any] | None) -> str:
    tags = set(item.get("queue_tags") or [])
    defaults = (pack or {}).get("classification", {}).get("defaults", {}) if pack else {}
    broadcast_default = str(defaults.get("broadcast", "reference") if isinstance(defaults, dict) else "reference")
    axes = _axes(item)
    # Owner-action claims without validated evidence stay watch (待确认), not action_required.
    if "pending" in tags and (item.get("evidence_basis") == "insufficient" or item.get("action_target")):
        return "watch"
    if "pending" in tags or (axes["urgency"] == "high" and axes["actionability"] == "high"):
        return "action_required"
    if "urgent" in tags or "sla_risk" in tags or item.get("action_hint"):
        return "watch"
    if axes["urgency"] == "high" and axes["actionability"] == "low":
        return "watch"
    return broadcast_default if broadcast_default in {"action_required", "watch", "reference"} else "reference"


def attach_projections(pulse: dict[str, Any], state_root: Path) -> dict[str, Any]:
    pack = load_active_pack(state_root)
    buckets = {"action_required": [], "watch": [], "reference": []}
    for key in ("needs_attention", "recent_activity", "thread_index"):
        rows = pulse.get(key)
        if not isinstance(rows, list):
            continue
        for item in rows:
            if not isinstance(item, dict):
                continue
            bucket = project_item(item, pack)
            item["projection"] = bucket
            item["axes"] = _axes(item)
            if not item.get("why"):
                item["why"] = f"projection={bucket}"
            if key == "needs_attention":
                buckets[bucket].append({
                    "thread_key": item.get("thread_key"),
                    "why": item.get("why"),
                    "projection": bucket,
                    "axes": item["axes"],
                    "action_hint": item.get("action_hint"),
                    "recipient_role": item.get("recipient_role"),
                })
    pulse["projections"] = {k: v[:20] for k, v in buckets.items()}
    return pulse
