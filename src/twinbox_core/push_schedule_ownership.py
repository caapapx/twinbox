"""Schedule enable/disable driven by push subscription cadence ownership."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from twinbox_core.push_subscription import load_subscriptions
from twinbox_core.schedule_override import (
    DEFAULT_TIMEZONE,
    disable_schedule,
    enable_schedule,
    load_schedule_config,
    load_schedule_overrides,
    update_schedule_override,
)

CadenceNeed = Literal["daily", "weekly"]


def any_subscription_needs(state_root: Path, cadence: CadenceNeed) -> bool:
    for sub in load_subscriptions(state_root):
        if not sub.enabled:
            continue
        if cadence == "daily" and sub.cadences.daily:
            return True
        if cadence == "weekly" and sub.cadences.weekly:
            return True
    return False


def sync_schedules_for_subscriptions(state_root: Path) -> dict[str, Any]:
    """Enable/disable daily-refresh and weekly-refresh from subscription aggregate."""
    results: dict[str, Any] = {}
    for cadence, job_name in (("daily", "daily-refresh"), ("weekly", "weekly-refresh")):
        need = any_subscription_needs(state_root, cadence)
        if need:
            payload = enable_schedule(state_root=state_root, job_name=job_name)
        else:
            payload = disable_schedule(state_root=state_root, job_name=job_name)
        results[job_name] = payload
    return results


def ensure_hourly_daily_refresh_if_needed(state_root: Path) -> dict[str, Any] | None:
    """When first enabling daily push and no cron override exists, set hourly."""
    overrides = load_schedule_overrides(state_root)
    omap = overrides.get("overrides", {})
    if isinstance(omap, dict) and "daily-refresh" in omap:
        return None
    cfg = load_schedule_config(state_root)
    tz = str(cfg.get("timezone", DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE)
    out = update_schedule_override(
        state_root=state_root,
        job_name="daily-refresh",
        cron="0 * * * *",
    )
    out["timezone_applied"] = tz
    out["reason"] = "first_daily_push_default_hourly"
    return out
