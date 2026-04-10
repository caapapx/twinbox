"""User-managed queue visibility state (dismiss / complete / restore)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def _queue_path(state_root: Path) -> Path:
    return state_root / "runtime" / "context" / "user-queue-state.yaml"


def load_queue_state(state_root: Path) -> dict[str, list[dict[str, Any]]]:
    path = _queue_path(state_root)
    if not path.is_file():
        return {"dismissed": [], "completed": []}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"dismissed": [], "completed": []}
    return {
        "dismissed": payload.get("dismissed", []) if isinstance(payload.get("dismissed"), list) else [],
        "completed": payload.get("completed", []) if isinstance(payload.get("completed"), list) else [],
    }


def _save(state_root: Path, payload: dict[str, list[dict[str, Any]]]) -> None:
    path = _queue_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _without(rows: list[dict[str, Any]], thread_key: str) -> list[dict[str, Any]]:
    return [r for r in rows if str(r.get("thread_key", "")) != thread_key]


def dismiss_thread(state_root: Path, thread_key: str, reason: str = "已处理") -> dict[str, Any]:
    payload = load_queue_state(state_root)
    payload["dismissed"] = _without(payload["dismissed"], thread_key)
    payload["completed"] = _without(payload["completed"], thread_key)
    payload["dismissed"].append({
        "thread_key": thread_key,
        "dismissed_at": _now_iso(),
        "reason": reason,
    })
    _save(state_root, payload)
    return {"ok": True, "action": "dismissed", "thread_key": thread_key}


def complete_thread(state_root: Path, thread_key: str, action_taken: str = "已完成") -> dict[str, Any]:
    payload = load_queue_state(state_root)
    payload["dismissed"] = _without(payload["dismissed"], thread_key)
    payload["completed"] = _without(payload["completed"], thread_key)
    payload["completed"].append({
        "thread_key": thread_key,
        "completed_at": _now_iso(),
        "action_taken": action_taken,
    })
    _save(state_root, payload)
    return {"ok": True, "action": "completed", "thread_key": thread_key}


def restore_thread(state_root: Path, thread_key: str) -> dict[str, Any]:
    payload = load_queue_state(state_root)
    payload["dismissed"] = _without(payload["dismissed"], thread_key)
    payload["completed"] = _without(payload["completed"], thread_key)
    _save(state_root, payload)
    return {"ok": True, "action": "restored", "thread_key": thread_key}
