"""Transactional push_subscription completion (CLI + OpenClaw tools)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from twinbox_core.host_bridge import host_bridge_status
from twinbox_core.onboarding import OnboardingStage, complete_stage, load_state, save_state
from twinbox_core.push_schedule_ownership import (
    ensure_hourly_daily_refresh_if_needed,
    sync_schedules_for_subscriptions,
)
from twinbox_core.push_subscription import subscribe


def confirm_push_subscription(
    state_root: Path,
    session_target: str,
    *,
    daily: bool = True,
    weekly: bool = True,
    openclaw_bin: str = "openclaw",
    twinbox_bin: str | None = None,
) -> dict[str, Any]:
    sr = state_root.expanduser().resolve()
    bridge = host_bridge_status(state_root=sr, openclaw_bin=openclaw_bin, twinbox_bin=twinbox_bin)
    timer_ok = bool(bridge.get("timer_enabled"))

    if not timer_ok:
        return {
            "ok": False,
            "error": "bridge_timer_not_enabled",
            "bridge_status": bridge,
            "daily_enabled": daily,
            "weekly_enabled": weekly,
        }

    sub = subscribe(sr, session_target, daily=daily, weekly=weekly)
    schedule_sync: dict[str, Any] = {}
    hourly_note: dict[str, Any] | None = None
    if daily:
        hourly_note = ensure_hourly_daily_refresh_if_needed(sr)
        schedule_sync = sync_schedules_for_subscriptions(sr)
    else:
        schedule_sync = sync_schedules_for_subscriptions(sr)

    state = load_state(sr)
    previous_stage: OnboardingStage = state.current_stage  # type: ignore[assignment]
    if state.current_stage == "push_subscription":
        complete_stage(state, "push_subscription")
        save_state(sr, state)

    return {
        "ok": True,
        "completed_stage": "push_subscription" if previous_stage == "push_subscription" else previous_stage,
        "current_stage": state.current_stage,
        "completed_stages": state.completed_stages,
        "bridge_status": bridge,
        "bridge_ready": timer_ok,
        "daily_enabled": sub.cadences.daily,
        "weekly_enabled": sub.cadences.weekly,
        "subscription": sub.to_dict(),
        "schedule_ownership": schedule_sync,
        "hourly_override": hourly_note,
    }
