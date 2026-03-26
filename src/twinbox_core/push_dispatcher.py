#!/usr/bin/env python3
"""
Push notification dispatcher.

Triggered by daytime_slice after activity-pulse.json generation.
Sends notifications to subscribed OpenClaw sessions via sessions_send.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .push_subscription import get_active_subscriptions, load_subscriptions, save_subscriptions


def dispatch_push(state_root: Path, payload: dict[str, Any], openclaw_bin: str = "openclaw") -> dict:
    """
    Dispatch push notifications to active subscriptions.

    Returns summary: {sent: int, failed: int, skipped: int}
    """
    subs = get_active_subscriptions(state_root)
    if not subs:
        return {"sent": 0, "failed": 0, "skipped": 0}

    notify = payload.get("notify_payload", {})
    summary = notify.get("summary", "")
    urgent_count = len(notify.get("urgent_top_k", []))

    if urgent_count == 0:
        return {"sent": 0, "failed": 0, "skipped": len(subs)}

    result = {"sent": 0, "failed": 0, "skipped": 0}
    message = f"📬 {summary}"

    for sub in subs:
        try:
            subprocess.run(
                [openclaw_bin, "sessions", "send", sub.session_id, message],
                check=True,
                capture_output=True,
                timeout=10,
            )
            sub.push_count += 1
            sub.last_push_at = payload.get("generated_at")
            result["sent"] += 1
        except Exception:
            result["failed"] += 1

    all_subs = load_subscriptions(state_root)
    save_subscriptions(state_root, all_subs)

    return result
