#!/usr/bin/env python3
"""
Push notification dispatcher (cadence-aware: daily / weekly).

Daily: urgent + pending action surface, per-session fingerprint dedupe, backlog rotation.
Weekly: full weekly-brief.md after friday-weekly, deduped by schedule run_id.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .daytime_slice import SHANGHAI, list_push_daily_candidates, phase4_dir
from .push_subscription import load_subscriptions, save_subscriptions


def _parse_ts(text: str | None) -> datetime | None:
    if not text or not str(text).strip():
        return None
    normalized = str(text).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=SHANGHAI)
    return dt


def _filter_since_push(candidates: list[dict[str, Any]], since: str | None) -> list[dict[str, Any]]:
    cutoff = _parse_ts(since)
    if cutoff is None:
        return candidates
    out: list[dict[str, Any]] = []
    for row in candidates:
        la = _parse_ts(str(row.get("last_activity_at", "") or ""))
        if la is None or la >= cutoff:
            out.append(row)
    return out


def _build_daily_message(to_send: list[dict[str, Any]], summary_line: str) -> str:
    lines = [f"📬 {summary_line}"]
    for item in to_send:
        tk = item.get("thread_key", "")
        why = str(item.get("why", "") or "").strip()
        lines.append(f"- {tk}: {why}" if why else f"- {tk}")
    return "\n".join(lines)


def dispatch_push_daily(
    state_root: Path,
    pulse_payload: dict[str, Any],
    *,
    openclaw_bin: str = "openclaw",
    max_threads: int = 3,
) -> dict[str, Any]:
    """Dispatch daily push for subscriptions with cadences.daily."""
    all_subs = load_subscriptions(state_root)
    subs = [s for s in all_subs if s.enabled and s.cadences.daily]
    if not subs:
        return {
            "cadence": "daily",
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "reason": "no_active_daily_subscriptions",
        }

    candidates = list_push_daily_candidates(state_root, window_hours=24)
    notify = pulse_payload.get("notify_payload", {})
    if not isinstance(notify, dict):
        notify = {}
    default_summary = str(notify.get("summary", "") or "Twinbox 日间推送")

    result: dict[str, Any] = {
        "cadence": "daily",
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "sessions": [],
    }

    for sub in subs:
        since = sub.delivery_state.daily.last_successful_push_at
        pool = _filter_since_push(candidates, since)
        fp_map = dict(sub.delivery_state.daily.delivered_fingerprints)
        eligible: list[dict[str, Any]] = []
        for row in pool:
            tk = str(row.get("thread_key", "") or "")
            if not tk:
                continue
            fp = str(row.get("fingerprint", "") or "")
            if fp_map.get(tk) == fp:
                continue
            eligible.append(row)

        score_index = {str(r.get("thread_key")): int(r.get("score", 0) or 0) for r in eligible}
        backlog = [k for k in sub.delivery_state.daily.backlog if k in score_index]
        seen = set(backlog)
        rest = sorted(
            (r for r in eligible if str(r.get("thread_key")) not in seen),
            key=lambda r: (int(r.get("score", 0) or 0), str(r.get("last_activity_at", ""))),
            reverse=True,
        )
        order_keys: list[str] = list(backlog) + [str(r.get("thread_key")) for r in rest]
        to_send_rows: list[dict[str, Any]] = []
        for tk in order_keys:
            row = next((r for r in eligible if str(r.get("thread_key")) == tk), None)
            if row is not None:
                to_send_rows.append(row)
            if len(to_send_rows) >= max_threads:
                break

        if not to_send_rows:
            result["skipped"] += 1
            result["sessions"].append(
                {
                    "session_target": sub.session_target,
                    "status": "skipped",
                    "reason": "no_notifiable_items",
                }
            )
            new_backlog = [k for k in order_keys if k not in {str(r.get("thread_key")) for r in to_send_rows}]
            sub.delivery_state.daily.backlog = new_backlog
            sub.delivery_state.daily.backlog_cursor = 0
            continue

        remaining = max(0, len(eligible) - len(to_send_rows))
        summary_line = default_summary
        if remaining:
            summary_line = f"{summary_line}（还有 {remaining} 条）"
        message = _build_daily_message(to_send_rows, summary_line)

        try:
            subprocess.run(
                [openclaw_bin, "sessions", "send", sub.session_target, message],
                check=True,
                capture_output=True,
                timeout=30,
            )
            sub.push_count += 1
            sub.last_push_at = pulse_payload.get("generated_at")
            sub.delivery_state.daily.last_successful_push_at = str(
                pulse_payload.get("generated_at") or notify.get("generated_at") or ""
            )
            for row in to_send_rows:
                tk = str(row.get("thread_key"))
                sub.delivery_state.daily.delivered_fingerprints[tk] = str(row.get("fingerprint", ""))
            sent_keys = {str(r.get("thread_key")) for r in to_send_rows}
            sub.delivery_state.daily.backlog = [k for k in order_keys if k not in sent_keys]
            sub.delivery_state.daily.backlog_cursor = 0
            result["sent"] += 1
            result["sessions"].append({"session_target": sub.session_target, "status": "sent", "threads": len(to_send_rows)})
        except Exception as exc:
            result["failed"] += 1
            result["sessions"].append(
                {"session_target": sub.session_target, "status": "failed", "error": str(exc)}
            )

    save_subscriptions(state_root, all_subs)
    return result


def dispatch_push_weekly(
    state_root: Path,
    *,
    run_id: str,
    openclaw_bin: str = "openclaw",
) -> dict[str, Any]:
    """Push full weekly-brief.md to weekly-enabled subscriptions."""
    all_subs = load_subscriptions(state_root)
    subs = [s for s in all_subs if s.enabled and s.cadences.weekly]
    brief_path = phase4_dir(state_root) / "weekly-brief.md"
    if not brief_path.is_file():
        return {
            "cadence": "weekly",
            "sent": 0,
            "failed": 0,
            "skipped": len(subs),
            "reason": "weekly_brief_missing",
        }

    text = brief_path.read_text(encoding="utf-8")
    message = f"📰 Twinbox 周报\n\n{text}"
    result: dict[str, Any] = {
        "cadence": "weekly",
        "run_id": run_id,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "sessions": [],
    }

    for sub in subs:
        if sub.delivery_state.weekly.last_run_id == run_id:
            result["skipped"] += 1
            result["sessions"].append(
                {"session_target": sub.session_target, "status": "skipped", "reason": "duplicate_run_id"}
            )
            continue
        try:
            subprocess.run(
                [openclaw_bin, "sessions", "send", sub.session_target, message],
                check=True,
                capture_output=True,
                timeout=60,
            )
            sub.delivery_state.weekly.last_run_id = run_id
            sub.push_count += 1
            result["sent"] += 1
            result["sessions"].append({"session_target": sub.session_target, "status": "sent"})
        except Exception as exc:
            result["failed"] += 1
            result["sessions"].append(
                {"session_target": sub.session_target, "status": "failed", "error": str(exc)}
            )

    save_subscriptions(state_root, all_subs)
    return result


def dispatch_push(state_root: Path, payload: dict[str, Any], openclaw_bin: str = "openclaw") -> dict[str, Any]:
    """Backward-compatible alias: daily dispatch from activity pulse job."""
    return dispatch_push_daily(state_root, payload, openclaw_bin=openclaw_bin)
