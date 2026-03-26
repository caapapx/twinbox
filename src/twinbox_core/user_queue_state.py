"""User-managed queue visibility state for thread-level pulse filtering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .artifacts import generated_at


def user_queue_state_path(state_root: Path) -> Path:
    return state_root / "runtime" / "context" / "user-queue-state.yaml"


def load_user_queue_state(state_root: Path) -> dict[str, list[dict[str, Any]]]:
    path = user_queue_state_path(state_root)
    if not path.is_file():
        return {"dismissed": [], "completed": []}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"dismissed": [], "completed": []}
    dismissed = payload.get("dismissed", [])
    completed = payload.get("completed", [])
    return {
        "dismissed": dismissed if isinstance(dismissed, list) else [],
        "completed": completed if isinstance(completed, list) else [],
    }


def save_user_queue_state(state_root: Path, payload: dict[str, list[dict[str, Any]]]) -> Path:
    path = user_queue_state_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _without_thread(rows: list[dict[str, Any]], thread_key: str) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("thread_key", "") or "") != thread_key]


def dismiss_thread(
    *,
    state_root: Path,
    thread_key: str,
    snapshot: dict[str, Any],
    reason: str,
    dismissed_from_queue: str,
) -> dict[str, list[dict[str, Any]]]:
    payload = load_user_queue_state(state_root)
    payload["dismissed"] = _without_thread(payload["dismissed"], thread_key)
    payload["completed"] = _without_thread(payload["completed"], thread_key)
    payload["dismissed"].append(
        {
            "thread_key": thread_key,
            "dismissed_at": generated_at(),
            "reason": reason,
            "dismissed_from_queue": dismissed_from_queue,
            "snapshot": snapshot,
        }
    )
    save_user_queue_state(state_root, payload)
    return payload


def complete_thread(
    *,
    state_root: Path,
    thread_key: str,
    snapshot: dict[str, Any],
    action_taken: str,
) -> dict[str, list[dict[str, Any]]]:
    payload = load_user_queue_state(state_root)
    payload["dismissed"] = _without_thread(payload["dismissed"], thread_key)
    payload["completed"] = _without_thread(payload["completed"], thread_key)
    payload["completed"].append(
        {
            "thread_key": thread_key,
            "completed_at": generated_at(),
            "action_taken": action_taken,
            "snapshot": snapshot,
        }
    )
    save_user_queue_state(state_root, payload)
    return payload


def restore_thread(*, state_root: Path, thread_key: str) -> dict[str, list[dict[str, Any]]]:
    payload = load_user_queue_state(state_root)
    payload["dismissed"] = _without_thread(payload["dismissed"], thread_key)
    payload["completed"] = _without_thread(payload["completed"], thread_key)
    save_user_queue_state(state_root, payload)
    return payload


def check_reactivation(*, state_root: Path, thread_key: str, fingerprint: str) -> bool:
    payload = load_user_queue_state(state_root)
    dismissed = payload["dismissed"]
    kept: list[dict[str, Any]] = []
    reactivated = False
    for row in dismissed:
        current_thread_key = str(row.get("thread_key", "") or "")
        previous_fingerprint = str(((row.get("snapshot") or {}).get("fingerprint", "")) or "")
        if current_thread_key == thread_key and previous_fingerprint != fingerprint:
            reactivated = True
            continue
        kept.append(row)
    if reactivated:
        payload["dismissed"] = kept
        save_user_queue_state(state_root, payload)
    return reactivated


def filter_thread_snapshots(
    *,
    state_root: Path,
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payload = load_user_queue_state(state_root)
    completed = {
        str(row.get("thread_key", "") or "")
        for row in payload["completed"]
        if isinstance(row, dict)
    }
    dismissed = {
        str(row.get("thread_key", "") or ""): str(((row.get("snapshot") or {}).get("fingerprint", "")) or "")
        for row in payload["dismissed"]
        if isinstance(row, dict)
    }

    visible: list[dict[str, Any]] = []
    changed = False
    for snapshot in snapshots:
        thread_key = str(snapshot.get("thread_key", "") or "")
        fingerprint = str(snapshot.get("fingerprint", "") or "")
        if thread_key in completed:
            continue
        previous_fingerprint = dismissed.get(thread_key)
        if previous_fingerprint is None:
            visible.append(snapshot)
            continue
        if previous_fingerprint == fingerprint:
            continue
        check_reactivation(state_root=state_root, thread_key=thread_key, fingerprint=fingerprint)
        changed = True
        visible.append(snapshot)

    if changed:
        payload = load_user_queue_state(state_root)
        save_user_queue_state(state_root, payload)
    return visible
