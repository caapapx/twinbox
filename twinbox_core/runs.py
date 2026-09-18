"""Bounded sync-run history and safe error classification."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

# Fixed stage error classes — no bodies, credentials, or auth headers in payloads.
ERROR_CLASSES = (
    "imap_connect",
    "imap_envelope",
    "imap_body",
    "embedding",
    "analysis_request",
    "analysis_parse",
    "pulse_write",
    "queue_join",
    "unknown",
)

MAX_RUN_HISTORY = 50
_SAFE_MSG = re.compile(r"(?i)\b(password|passwd|secret|token|authorization|bearer)\b\s*[:=]\s*\S+.*")


def new_run_id() -> str:
    return uuid.uuid4().hex[:16]


def _now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def sanitize_error_message(message: str, *, limit: int = 240) -> str:
    text = str(message or "")
    text = _SAFE_MSG.sub(r"\1=[redacted]", text)
    text = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", text)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def classify_error(*, step: str = "", message: str = "", degraded: list[str] | None = None) -> str:
    step_l = (step or "").lower()
    msg_l = (message or "").lower()
    degraded = degraded or []

    if step_l in {"fetch", "imap"} or "imap" in msg_l or "connection" in msg_l:
        if any(k in msg_l for k in ("login", "auth", "credential", "connect", "ssl", "tls", "refused", "timeout")):
            return "imap_connect"
        if any(k in msg_l for k in ("envelope", "header", "decode", "cr or lf", "linefeed", "carriage")):
            return "imap_envelope"
        if "body" in msg_l or "rfc822" in msg_l or "fetch" in msg_l:
            return "imap_body"
        return "imap_connect"
    if step_l in {"embed", "embedding"} or "embed" in msg_l:
        return "embedding"
    if step_l in {"analysis", "analyze"} or "analysis" in degraded:
        if any(k in msg_l for k in ("json", "parse", "decode", "schema")):
            return "analysis_parse"
        return "analysis_request"
    if step_l in {"pulse"} or "pulse" in msg_l:
        return "pulse_write"
    if step_l in {"queue"} or "queue_join" in msg_l:
        return "queue_join"
    return "unknown"


def runs_dir(account_root: Path) -> Path:
    return account_root / "runtime" / "runs"


def history_path(account_root: Path) -> Path:
    return runs_dir(account_root) / "history.jsonl"


def last_run_path(account_root: Path) -> Path:
    return runs_dir(account_root) / "last-run.json"


def append_run(account_root: Path, record: dict[str, Any], *, keep: int = MAX_RUN_HISTORY) -> dict[str, Any]:
    """Append one run summary and roll history. Never stores mail bodies."""
    path = history_path(account_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = bool(record.get("ok"))
    attempted_at = record.get("attempted_at") or _now_iso()
    finished_at = record.get("finished_at") or _now_iso()
    success_at = record.get("success_at")
    if ok and not success_at:
        success_at = finished_at
    row = {
        "run_id": record.get("run_id") or new_run_id(),
        "account_id": record.get("account_id") or "default",
        "job": record.get("job") or "",
        "ok": ok,
        "attempted_at": attempted_at,
        "finished_at": finished_at,
        "success_at": success_at if ok else None,
        "degraded": list(record.get("degraded") or []),
        "error_class": record.get("error_class"),
        "error": sanitize_error_message(str(record.get("error") or "")) if record.get("error") else None,
        "timings_ms": record.get("timings_ms") if isinstance(record.get("timings_ms"), dict) else {},
        "stages": record.get("stages") if isinstance(record.get("stages"), dict) else {},
        "select": record.get("select") if isinstance(record.get("select"), dict) else None,
        "analysis_path": record.get("analysis_path") if record.get("analysis_path") in {"skip", "incremental", "full", "quick"} else None,
        "new_envelope_count": record.get("new_envelope_count") if record.get("new_envelope_count") is None or isinstance(record.get("new_envelope_count"), int) else None,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(lines) > keep:
        path.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")

    last_run_path(account_root).write_text(
        json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return row


def load_recent_runs(account_root: Path, *, limit: int = 20) -> list[dict[str, Any]]:
    path = history_path(account_root)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-max(1, limit) :]


def load_last_run(account_root: Path) -> dict[str, Any] | None:
    path = last_run_path(account_root)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, OSError):
            pass
    recent = load_recent_runs(account_root, limit=1)
    return recent[-1] if recent else None


def _mtime_iso(path: Path) -> str | None:
    if not path.is_file():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=SHANGHAI).isoformat(timespec="seconds")


def _nonempty_iso(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _artifact_generated_at(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        if path.suffix in {".yaml", ".yml"}:
            import yaml
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, Exception):
        return None
    if isinstance(data, dict):
        return _nonempty_iso(data.get("generated_at"))
    return None


def account_freshness(account_root: Path) -> dict[str, Any]:
    """Attempt vs success freshness for one account namespace."""
    last = load_last_run(account_root) or {}
    context = account_root / "runtime" / "context" / "phase1-context.json"
    analysis = account_root / "runtime" / "validation" / "phase-4" / "pending-replies.yaml"
    pulse = account_root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
    pulse_data: dict[str, Any] = {}
    if pulse.is_file():
        try:
            raw = json.loads(pulse.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            raw = {}
        if isinstance(raw, dict):
            pulse_data = raw
    return {
        "last_attempt_at": last.get("attempted_at"),
        "last_success_at": last.get("success_at"),
        "last_fetch_at": _nonempty_iso(pulse_data.get("fetch_at")) or _artifact_generated_at(context),
        "last_analysis_at": _nonempty_iso(pulse_data.get("analysis_generated_at")) or _artifact_generated_at(analysis),
        "last_pulse_at": _nonempty_iso(pulse_data.get("generated_at")) or _mtime_iso(pulse),
        "last_run_ok": last.get("ok"),
        "last_error_class": last.get("error_class"),
        "degraded": list(last.get("degraded") or []),
        "last_run_id": last.get("run_id"),
    }


