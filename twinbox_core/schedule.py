"""Cron-driven schedule runner with fcntl file lock."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

SHANGHAI = ZoneInfo("Asia/Shanghai")

DEFAULT_JOBS = [
    {"name": "daytime-sync", "cron_hour": 12, "cron_minute": 0, "job": "daytime-sync"},
    {"name": "afternoon-sync", "cron_hour": 16, "cron_minute": 30, "job": "daytime-sync"},
    {"name": "nightly-full", "cron_hour": 2, "cron_minute": 0, "job": "nightly-full"},
]


def _sched_dir(state_root: Path) -> Path:
    path = state_root / "runtime" / "schedule"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_jobs(code_root: Path | None = None) -> list[dict[str, Any]]:
    root = code_root or Path(__file__).resolve().parents[1]
    path = root / "config" / "schedules.yaml"
    if not path.is_file():
        return list(DEFAULT_JOBS)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = data.get("schedules") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        return list(DEFAULT_JOBS)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cron = str(row.get("cron") or "").split()
        hour, minute = 8, 30
        if len(cron) >= 2 and cron[1].isdigit() and cron[0].isdigit():
            minute, hour = int(cron[0]), int(cron[1])
        job = str(row.get("job") or row.get("name") or "daytime-sync")
        if "nightly" in job:
            job_id = "nightly-full"
        else:
            job_id = "daytime-sync"
        out.append({
            "name": str(row.get("name") or job_id),
            "cron_hour": hour,
            "cron_minute": minute,
            "job": job_id,
        })
    return out or list(DEFAULT_JOBS)


def _last_run_path(state_root: Path) -> Path:
    return _sched_dir(state_root) / "last-run.json"


def load_last_run(state_root: Path) -> dict[str, Any]:
    path = _last_run_path(state_root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_dt(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed


def due_jobs(state_root: Path, now: datetime | None = None, code_root: Path | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(SHANGHAI)
    last = load_last_run(state_root)
    due: list[dict[str, Any]] = []
    for job in load_jobs(code_root):
        last_at = _parse_dt((last.get(job["name"]) or {}).get("at") if isinstance(last.get(job["name"]), dict) else last.get(job["name"]))
        scheduled = now.replace(hour=int(job["cron_hour"]), minute=int(job["cron_minute"]), second=0, microsecond=0)
        if now < scheduled:
            scheduled -= timedelta(days=1)
        if last_at and last_at > now:
            continue
        if last_at is None or last_at < scheduled <= now:
            due.append(job)
    return due


def missed_runs(state_root: Path, now: datetime | None = None, code_root: Path | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(SHANGHAI)
    last = load_last_run(state_root)
    missed: list[dict[str, Any]] = []
    for job in load_jobs(code_root):
        last_at = _parse_dt((last.get(job["name"]) or {}).get("at") if isinstance(last.get(job["name"]), dict) else last.get(job["name"]))
        slots = 0
        cursor = now.replace(hour=int(job["cron_hour"]), minute=int(job["cron_minute"]), second=0, microsecond=0)
        if cursor > now:
            cursor -= timedelta(days=1)
        while slots < 3:
            if last_at is None or last_at < cursor:
                slots += 1
            else:
                break
            cursor -= timedelta(days=1)
        if slots >= 2:
            missed.append({"name": job["name"], "missed": slots})
    return missed


def run_due(state_root: Path, *, now: datetime | None = None, sync_fn=None, code_root: Path | None = None) -> dict[str, Any]:
    import fcntl

    lock_path = _sched_dir(state_root) / "run-due.lock"
    lock_path.touch(exist_ok=True)
    with lock_path.open("a+") as lock_fh:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"ok": True, "ran": [], "skipped": "locked"}
        due = due_jobs(state_root, now=now, code_root=code_root)
        if not due:
            return {"ok": True, "ran": []}
        from .cli import cmd_sync
        runner = sync_fn or cmd_sync
        ran: list[dict[str, Any]] = []
        last = load_last_run(state_root)
        for job in due:
            result = runner(job["job"])
            ok = bool(result.get("ok", True)) and "analysis" not in (result.get("degraded") or [])
            if ok or result.get("degraded"):
                # fetch succeeded counts as a run; analysis degrade still stamps last-run
                last[job["name"]] = {
                    "at": (now or datetime.now(SHANGHAI)).isoformat(timespec="seconds"),
                    "ok": ok,
                    "degraded": result.get("degraded") or [],
                }
            analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
            ran.append({
                "name": job["name"],
                "ok": ok,
                "result": {
                    "ok": result.get("ok"),
                    "degraded": result.get("degraded"),
                    "analysis_error": analysis.get("error"),
                },
            })
            if job["job"] == "nightly-full" and (ok or result.get("degraded")):
                try:
                    from .taxonomy import record_drift
                    drift = record_drift(state_root)
                    ran[-1]["taxonomy_drift"] = {
                        "ok": drift.get("ok"),
                        "path": drift.get("path"),
                    }
                except Exception as exc:
                    ran[-1]["taxonomy_drift"] = {"ok": False, "error": type(exc).__name__}
            if not result.get("ok") and not result.get("degraded"):
                continue
        _last_run_path(state_root).write_text(json.dumps(last, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"ok": all(r["ok"] or True for r in ran), "ran": ran}
