"""Host-side poller for OpenClaw cron/system-event bridge runs."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from twinbox_core.daytime_slice import generated_at


class OpenClawBridgeError(RuntimeError):
    """Raised when OpenClaw cron bridge polling fails."""


@dataclass(frozen=True)
class OpenClawCronRun:
    """One OpenClaw cron run entry eligible for Twinbox dispatch."""

    entry_key: str
    job_id: str
    summary: str
    ts: int
    run_at_ms: int | None


DispatchFn = Callable[[str, bool], tuple[int, dict[str, object]]]


def bridge_state_path(state_root: Path) -> Path:
    return state_root / "runtime" / "context" / "openclaw-bridge-state.json"


def bridge_audit_path(state_root: Path) -> Path:
    return state_root / "runtime" / "audit" / "openclaw-bridge-polls.jsonl"


def load_bridge_state(state_root: Path) -> dict[str, Any]:
    path = bridge_state_path(state_root)
    if not path.is_file():
        return {"processed_entry_keys": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"processed_entry_keys": []}
    if not isinstance(payload, dict):
        return {"processed_entry_keys": []}
    keys = payload.get("processed_entry_keys", [])
    if not isinstance(keys, list):
        keys = []
    payload["processed_entry_keys"] = [str(key) for key in keys if str(key).strip()]
    return payload


def save_bridge_state(state_root: Path, state: dict[str, Any]) -> Path:
    path = bridge_state_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = dict(state)
    keys = normalized.get("processed_entry_keys", [])
    if not isinstance(keys, list):
        keys = []
    normalized["processed_entry_keys"] = [str(key) for key in keys[-500:]]
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def append_bridge_audit(state_root: Path, record: dict[str, object]) -> Path:
    path = bridge_audit_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def _run_openclaw_json(argv: list[str]) -> dict[str, Any]:
    completed = subprocess.run(argv, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown OpenClaw gateway failure"
        raise OpenClawBridgeError(f"`{' '.join(argv)}` failed: {stderr}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise OpenClawBridgeError(f"OpenClaw gateway output is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise OpenClawBridgeError("OpenClaw gateway output must be a JSON object.")
    return payload


def run_openclaw_cron_list(*, openclaw_bin: str) -> dict[str, Any]:
    return _run_openclaw_json(
        [openclaw_bin, "gateway", "call", "cron.list", "--json", "--params", '{"includeDisabled":true}']
    )


def run_openclaw_cron_runs(*, openclaw_bin: str, limit: int, job_id: str) -> dict[str, Any]:
    params = json.dumps({"id": job_id, "limit": limit}, ensure_ascii=False)
    return _run_openclaw_json([openclaw_bin, "gateway", "call", "cron.runs", "--json", "--params", params])


def discover_bridge_job_ids(jobs_payload: dict[str, Any]) -> list[str]:
    jobs = jobs_payload.get("jobs", [])
    if not isinstance(jobs, list):
        raise OpenClawBridgeError("OpenClaw cron list payload is missing `jobs`.")
    job_ids: list[str] = []
    for row in jobs:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if payload.get("kind") != "systemEvent":
            continue
        text = str(payload.get("text", "") or "").strip()
        if not text:
            continue
        if not (text.startswith("{") or text.startswith("twinbox.schedule:") or text.startswith("twinbox.schedule ")):
            continue
        job_id = str(row.get("id", "") or "").strip()
        if job_id:
            job_ids.append(job_id)
    return job_ids


def discover_bridge_runs(
    runs_payload: dict[str, Any],
    *,
    processed_entry_keys: set[str],
) -> tuple[list[OpenClawCronRun], dict[str, int]]:
    entries = runs_payload.get("entries", [])
    if not isinstance(entries, list):
        raise OpenClawBridgeError("OpenClaw cron runs payload is missing `entries`.")

    discovered: list[OpenClawCronRun] = []
    counters = {
        "scanned_entries": 0,
        "processed_skipped": 0,
        "ignored_entries": 0,
    }
    for row in entries:
        counters["scanned_entries"] += 1
        if not isinstance(row, dict):
            counters["ignored_entries"] += 1
            continue
        if row.get("action") != "finished" or row.get("status") != "ok":
            counters["ignored_entries"] += 1
            continue
        summary = str(row.get("summary", "") or "").strip()
        if not summary:
            counters["ignored_entries"] += 1
            continue
        if not (summary.startswith("{") or summary.startswith("twinbox.schedule:") or summary.startswith("twinbox.schedule ")):
            counters["ignored_entries"] += 1
            continue
        entry_key = "|".join(
            (
                str(row.get("jobId", "") or ""),
                str(row.get("runAtMs", "") or ""),
                str(row.get("ts", "") or ""),
            )
        )
        if entry_key in processed_entry_keys:
            counters["processed_skipped"] += 1
            continue
        discovered.append(
            OpenClawCronRun(
                entry_key=entry_key,
                job_id=str(row.get("jobId", "") or ""),
                summary=summary,
                ts=int(row.get("ts", 0) or 0),
                run_at_ms=int(row["runAtMs"]) if isinstance(row.get("runAtMs"), int) else None,
            )
        )

    discovered.sort(key=lambda item: (item.ts, item.entry_key))
    return discovered, counters


def poll_openclaw_bridge(
    state_root: Path,
    *,
    dry_run: bool,
    limit: int,
    openclaw_bin: str,
    dispatch_event: DispatchFn,
) -> tuple[int, dict[str, object]]:
    started_at = generated_at()
    state = load_bridge_state(state_root)
    processed_entry_keys = set(str(key) for key in state.get("processed_entry_keys", []))
    jobs_payload = run_openclaw_cron_list(openclaw_bin=openclaw_bin)
    job_ids = discover_bridge_job_ids(jobs_payload)
    discovered: list[OpenClawCronRun] = []
    counters = {
        "scanned_entries": 0,
        "processed_skipped": 0,
        "ignored_entries": 0,
        "bridge_jobs": len(job_ids),
    }
    for job_id in job_ids:
        runs_payload = run_openclaw_cron_runs(openclaw_bin=openclaw_bin, limit=limit, job_id=job_id)
        job_discovered, job_counters = discover_bridge_runs(
            runs_payload,
            processed_entry_keys=processed_entry_keys,
        )
        discovered.extend(job_discovered)
        counters["scanned_entries"] += job_counters["scanned_entries"]
        counters["processed_skipped"] += job_counters["processed_skipped"]
        counters["ignored_entries"] += job_counters["ignored_entries"]

    dispatched: list[dict[str, object]] = []
    failed_count = 0
    for run in discovered:
        exit_code, payload = dispatch_event(run.summary, dry_run)
        dispatched.append(
            {
                "entry_key": run.entry_key,
                "job_id": run.job_id,
                "summary": run.summary,
                "run_ts": run.ts,
                "run_at_ms": run.run_at_ms,
                "exit_code": exit_code,
                "bridge_job": payload.get("bridge_event", {}).get("job"),
                "schedule_status": payload.get("schedule", {}).get("status"),
                "schedule_run_id": payload.get("schedule", {}).get("run_id"),
            }
        )
        if exit_code == 0:
            processed_entry_keys.add(run.entry_key)
        else:
            failed_count += 1

    finished_at = generated_at()
    status = "success"
    exit_code = 0
    if failed_count and dispatched:
        status = "partial_failure"
        exit_code = 1

    state_path = None
    audit_path = None
    if not dry_run:
        state["processed_entry_keys"] = sorted(processed_entry_keys)
        state["last_polled_at"] = finished_at
        state["last_status"] = status
        state["last_dispatched_count"] = len(dispatched)
        state_path = str(save_bridge_state(state_root, state))
        audit_record = {
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "limit": limit,
            "openclaw_bin": openclaw_bin,
            **counters,
            "dispatched_count": len(dispatched),
            "failed_count": failed_count,
            "results": dispatched,
        }
        audit_path = str(append_bridge_audit(state_root, audit_record))

    payload = {
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "limit": limit,
        "openclaw_bin": openclaw_bin,
        **counters,
        "dispatched_count": len(dispatched),
        "failed_count": failed_count,
        "results": dispatched,
        "artifact_paths": {
            "bridge_state": state_path,
            "bridge_audit": audit_path,
        },
    }
    return exit_code, payload
