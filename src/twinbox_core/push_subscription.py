#!/usr/bin/env python3
"""
Push notification subscription management (cadence-aware: daily / weekly).

Anti-spam layers:
1. Fingerprint deduplication (activity pulse + per-subscription state)
2. Rate limiting per session
3. User-controlled subscription state per cadence
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


@dataclass
class CadenceState:
    """Per-cadence on/off."""

    daily: bool = True
    weekly: bool = True

    def to_dict(self) -> dict[str, bool]:
        return {"daily": self.daily, "weekly": self.weekly}

    @classmethod
    def from_dict(cls, data: object) -> CadenceState:
        if not isinstance(data, dict):
            return cls()
        return cls(
            daily=bool(data.get("daily", True)),
            weekly=bool(data.get("weekly", True)),
        )


@dataclass
class DailyDeliveryState:
    last_successful_push_at: str | None = None
    backlog: list[str] = field(default_factory=list)
    delivered_fingerprints: dict[str, str] = field(default_factory=dict)
    backlog_cursor: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_successful_push_at": self.last_successful_push_at,
            "backlog": list(self.backlog),
            "delivered_fingerprints": dict(self.delivered_fingerprints),
            "backlog_cursor": self.backlog_cursor,
        }

    @classmethod
    def from_dict(cls, data: object) -> DailyDeliveryState:
        if not isinstance(data, dict):
            return cls()
        fp = data.get("delivered_fingerprints", {})
        if not isinstance(fp, dict):
            fp = {}
        bl = data.get("backlog", [])
        if not isinstance(bl, list):
            bl = []
        return cls(
            last_successful_push_at=data.get("last_successful_push_at"),
            backlog=[str(x) for x in bl if str(x).strip()],
            delivered_fingerprints={str(k): str(v) for k, v in fp.items()},
            backlog_cursor=int(data.get("backlog_cursor", 0) or 0),
        )


@dataclass
class WeeklyDeliveryState:
    last_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"last_run_id": self.last_run_id}

    @classmethod
    def from_dict(cls, data: object) -> WeeklyDeliveryState:
        if not isinstance(data, dict):
            return cls()
        return cls(last_run_id=data.get("last_run_id"))


@dataclass
class DeliveryState:
    daily: DailyDeliveryState = field(default_factory=DailyDeliveryState)
    weekly: WeeklyDeliveryState = field(default_factory=WeeklyDeliveryState)

    def to_dict(self) -> dict[str, Any]:
        return {
            "daily": self.daily.to_dict(),
            "weekly": self.weekly.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: object) -> DeliveryState:
        if not isinstance(data, dict):
            return cls()
        daily_raw = data.get("daily", {})
        weekly_raw = data.get("weekly", {})
        return cls(
            daily=DailyDeliveryState.from_dict(daily_raw),
            weekly=WeeklyDeliveryState.from_dict(weekly_raw),
        )


@dataclass
class PushSubscription:
    """Push notification subscription keyed by stable session target (e.g. OpenClaw session id)."""

    session_target: str
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    cadences: CadenceState = field(default_factory=CadenceState)
    delivery_state: DeliveryState = field(default_factory=DeliveryState)
    filters: dict[str, Any] = field(default_factory=dict)
    # Legacy counters (optional)
    last_push_at: str | None = None
    push_count: int = 0

    @property
    def session_id(self) -> str:
        return self.session_target

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_target": self.session_target,
            "enabled": self.enabled,
            "created_at": self.created_at,
            "cadences": self.cadences.to_dict(),
            "delivery_state": self.delivery_state.to_dict(),
            "filters": self.filters,
            "last_push_at": self.last_push_at,
            "push_count": self.push_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PushSubscription:
        st = str(data.get("session_target") or data.get("session_id") or "").strip()
        cadences = CadenceState.from_dict(data.get("cadences", {}))
        delivery = DeliveryState.from_dict(data.get("delivery_state", {}))
        # Migrate flat legacy
        if "cadences" not in data and "session_id" in data:
            en = data.get("enabled", True)
            cadences = CadenceState(daily=bool(en), weekly=bool(en))
        return cls(
            session_target=st,
            enabled=bool(data.get("enabled", True)),
            created_at=str(data.get("created_at", datetime.now().isoformat())),
            cadences=cadences,
            delivery_state=delivery,
            filters=dict(data.get("filters", {}) or {}),
            last_push_at=data.get("last_push_at"),
            push_count=int(data.get("push_count", 0) or 0),
        )


def get_subscriptions_path(state_root: Path) -> Path:
    return state_root / "runtime" / "push-subscriptions.json"


def _migrate_file_schema(raw: dict[str, Any]) -> dict[str, Any]:
    subs = raw.get("subscriptions", [])
    if not isinstance(subs, list):
        subs = []
    migrated: list[dict[str, Any]] = []
    for row in subs:
        if not isinstance(row, dict):
            continue
        migrated.append(PushSubscription.from_dict(row).to_dict())
    return {"subscriptions": migrated, "schema_version": 2}


def load_subscriptions(state_root: Path) -> list[PushSubscription]:
    path = get_subscriptions_path(state_root)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return []
        if int(data.get("schema_version", 1) or 1) < 2:
            data = _migrate_file_schema(data)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        rows = data.get("subscriptions", [])
        if not isinstance(rows, list):
            return []
        return [PushSubscription.from_dict(r) for r in rows if isinstance(r, dict)]
    except Exception:
        return []


def save_subscriptions(state_root: Path, subs: list[PushSubscription]) -> None:
    path = get_subscriptions_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 2, "subscriptions": [s.to_dict() for s in subs]}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def subscribe(
    state_root: Path,
    session_target: str,
    filters: dict[str, Any] | None = None,
    *,
    daily: bool = True,
    weekly: bool = True,
) -> PushSubscription:
    subs = load_subscriptions(state_root)
    existing = next((s for s in subs if s.session_target == session_target), None)
    if existing:
        existing.enabled = True
        existing.cadences.daily = daily
        existing.cadences.weekly = weekly
        if filters:
            existing.filters.update(filters)
        save_subscriptions(state_root, subs)
        return existing
    new_sub = PushSubscription(
        session_target=session_target,
        cadences=CadenceState(daily=daily, weekly=weekly),
        filters=filters or {},
    )
    subs.append(new_sub)
    save_subscriptions(state_root, subs)
    return new_sub


def unsubscribe(state_root: Path, session_target: str) -> bool:
    subs = load_subscriptions(state_root)
    target = next((s for s in subs if s.session_target == session_target), None)
    if target:
        target.enabled = False
        target.cadences.daily = False
        target.cadences.weekly = False
        save_subscriptions(state_root, subs)
        return True
    return False


def configure_cadences(
    state_root: Path,
    session_target: str,
    *,
    daily: bool | None = None,
    weekly: bool | None = None,
) -> PushSubscription | None:
    subs = load_subscriptions(state_root)
    target = next((s for s in subs if s.session_target == session_target), None)
    if not target:
        return None
    if daily is not None:
        target.cadences.daily = daily
    if weekly is not None:
        target.cadences.weekly = weekly
    target.enabled = target.cadences.daily or target.cadences.weekly
    save_subscriptions(state_root, subs)
    return target


def get_active_subscriptions(state_root: Path) -> list[PushSubscription]:
    return [s for s in load_subscriptions(state_root) if s.enabled]


def subscriptions_for_daily(state_root: Path) -> list[PushSubscription]:
    return [s for s in get_active_subscriptions(state_root) if s.cadences.daily]


def subscriptions_for_weekly(state_root: Path) -> list[PushSubscription]:
    return [s for s in get_active_subscriptions(state_root) if s.cadences.weekly]
