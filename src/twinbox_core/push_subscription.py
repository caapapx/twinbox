#!/usr/bin/env python3
"""
Push notification subscription management.

Anti-spam layers:
1. Fingerprint deduplication (already in daytime_slice.py)
2. Rate limiting per session
3. User-controlled subscription state
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal


@dataclass
class PushSubscription:
    """Push notification subscription."""

    session_id: str
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_push_at: str | None = None
    push_count: int = 0
    filters: dict = field(default_factory=dict)  # e.g., {"min_urgency": "high"}

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_push_at": self.last_push_at,
            "push_count": self.push_count,
            "filters": self.filters,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PushSubscription:
        return cls(
            session_id=data["session_id"],
            enabled=data.get("enabled", True),
            created_at=data.get("created_at", datetime.now().isoformat()),
            last_push_at=data.get("last_push_at"),
            push_count=data.get("push_count", 0),
            filters=data.get("filters", {}),
        )


def get_subscriptions_path(state_root: Path) -> Path:
    """Get push subscriptions file path."""
    return state_root / "runtime" / "push-subscriptions.json"


def load_subscriptions(state_root: Path) -> list[PushSubscription]:
    """Load all subscriptions."""
    path = get_subscriptions_path(state_root)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [PushSubscription.from_dict(s) for s in data.get("subscriptions", [])]
    except Exception:
        return []


def save_subscriptions(state_root: Path, subs: list[PushSubscription]) -> None:
    """Save subscriptions to disk."""
    path = get_subscriptions_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"subscriptions": [s.to_dict() for s in subs]}, f, ensure_ascii=False, indent=2)


def subscribe(state_root: Path, session_id: str, filters: dict | None = None) -> PushSubscription:
    """Subscribe a session to push notifications."""
    subs = load_subscriptions(state_root)
    existing = next((s for s in subs if s.session_id == session_id), None)
    if existing:
        existing.enabled = True
        if filters:
            existing.filters.update(filters)
        save_subscriptions(state_root, subs)
        return existing
    new_sub = PushSubscription(session_id=session_id, filters=filters or {})
    subs.append(new_sub)
    save_subscriptions(state_root, subs)
    return new_sub


def unsubscribe(state_root: Path, session_id: str) -> bool:
    """Unsubscribe a session."""
    subs = load_subscriptions(state_root)
    target = next((s for s in subs if s.session_id == session_id), None)
    if target:
        target.enabled = False
        save_subscriptions(state_root, subs)
        return True
    return False


def get_active_subscriptions(state_root: Path) -> list[PushSubscription]:
    """Get all active subscriptions."""
    return [s for s in load_subscriptions(state_root) if s.enabled]
