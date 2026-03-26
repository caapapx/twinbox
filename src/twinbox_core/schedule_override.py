"""Runtime schedule override helpers layered on top of SKILL.md defaults."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .orchestration import OrchestrationError, parse_bridge_event_text

DEFAULT_TIMEZONE = "Asia/Shanghai"
SCHEDULE_BINDINGS: dict[str, dict[str, str]] = {
    "daily-refresh": {
        "scheduled_job": "daytime-sync",
        "platform_name": "twinbox-daily-refresh",
    },
    "weekly-refresh": {
        "scheduled_job": "friday-weekly",
        "platform_name": "twinbox-weekly-refresh",
    },
    "nightly-full-refresh": {
        "scheduled_job": "nightly-full",
        "platform_name": "twinbox-nightly-full-refresh",
    },
}


def schedule_override_path(state_root: Path) -> Path:
    return state_root / "runtime" / "context" / "schedule-overrides.yaml"


def _repo_skill_path() -> Path:
    return Path(__file__).resolve().parents[2] / "SKILL.md"


def _read_frontmatter(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    frontmatter = text[4:end]
    payload = yaml.safe_load(frontmatter)
    return payload if isinstance(payload, dict) else {}


def load_schedule_defaults(skill_path: Path | None = None) -> dict[str, Any]:
    path = skill_path or _repo_skill_path()
    frontmatter = _read_frontmatter(path)
    metadata = frontmatter.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    openclaw = metadata.get("openclaw", {})
    if not isinstance(openclaw, dict):
        openclaw = {}
    schedules = openclaw.get("schedules", [])
    if not isinstance(schedules, list):
        schedules = []

    normalized: list[dict[str, str]] = []
    for row in schedules:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "") or "")
        cron = str(row.get("cron", "") or "")
        command = str(row.get("command", "") or "")
        description = str(row.get("description", "") or "")
        if not name or not cron:
            continue
        normalized.append(
            {
                "name": name,
                "cron": cron,
                "command": command,
                "description": description,
            }
        )

    return {"timezone": DEFAULT_TIMEZONE, "schedules": normalized}


def load_schedule_overrides(state_root: Path) -> dict[str, Any]:
    path = schedule_override_path(state_root)
    if not path.is_file():
        return {"timezone": DEFAULT_TIMEZONE, "overrides": {}}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"timezone": DEFAULT_TIMEZONE, "overrides": {}}
    timezone = str(payload.get("timezone", DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE)
    overrides = payload.get("overrides", {})
    if not isinstance(overrides, dict):
        overrides = {}
    return {
        "timezone": timezone,
        "overrides": {str(key): str(value) for key, value in overrides.items() if str(key)},
    }


def _write_schedule_overrides(state_root: Path, payload: dict[str, Any]) -> Path:
    path = schedule_override_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp_path.replace(path)
    return path


def validate_cron_expression(cron: str) -> str | None:
    text = str(cron or "").strip()
    fields = text.split()
    if len(fields) != 5:
        return "Cron expression must have exactly 5 fields."
    pattern = re.compile(r"^[\d\*/,\-]+$")
    for field in fields:
        if not pattern.match(field):
            return f"Unsupported cron field: {field}"
    return None


def _default_openclaw_runner(argv: list[str]) -> str:
    completed = subprocess.run(argv, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown OpenClaw CLI failure"
        raise RuntimeError(f"`{' '.join(argv)}` failed: {stderr}")
    return completed.stdout


def _schedule_binding(job_name: str, skill_path: Path | None = None) -> dict[str, str]:
    binding = SCHEDULE_BINDINGS.get(job_name)
    if not isinstance(binding, dict):
        raise ValueError(f"Unknown schedule: {job_name}")
    defaults = load_schedule_defaults(skill_path)
    current = next((row for row in defaults["schedules"] if row["name"] == job_name), None)
    if not isinstance(current, dict):
        raise ValueError(f"Unknown schedule: {job_name}")
    return {
        "job_name": job_name,
        "scheduled_job": binding["scheduled_job"],
        "platform_name": binding["platform_name"],
        "description": str(current.get("description", "") or ""),
    }


def _openclaw_system_event_text(scheduled_job: str) -> str:
    return json.dumps(
        {
            "kind": "twinbox.schedule",
            "job": scheduled_job,
            "event_source": "openclaw.system-event",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _matching_openclaw_job_ids(jobs_payload: dict[str, Any], scheduled_job: str) -> list[str]:
    jobs = jobs_payload.get("jobs", [])
    if not isinstance(jobs, list):
        raise RuntimeError("OpenClaw cron list payload is missing `jobs`.")
    matches: list[str] = []
    for row in jobs:
        if not isinstance(row, dict):
            continue
        job_id = str(row.get("id", "") or "").strip()
        payload = row.get("payload", {})
        if not job_id or not isinstance(payload, dict):
            continue
        if payload.get("kind") != "systemEvent":
            continue
        text = str(payload.get("text", "") or "").strip()
        if not text:
            continue
        try:
            event = parse_bridge_event_text(text)
        except OrchestrationError:
            continue
        if event.job_id == scheduled_job:
            matches.append(job_id)
    return matches


def _extract_openclaw_job_id(payload: dict[str, Any]) -> str:
    for candidate in (
        payload.get("id"),
        payload.get("job_id"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    job = payload.get("job")
    if isinstance(job, dict):
        text = str(job.get("id", "") or "").strip()
        if text:
            return text
    return ""


def sync_schedule_to_openclaw(
    *,
    job_name: str,
    cron: str,
    timezone: str,
    skill_path: Path | None = None,
    runner: Any = None,
) -> dict[str, Any]:
    binding = _schedule_binding(job_name, skill_path)
    run = runner or _default_openclaw_runner
    list_stdout = run(["openclaw", "cron", "list", "--all", "--json"])
    try:
        jobs_payload = json.loads(list_stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"OpenClaw cron list output is not valid JSON: {exc.msg}") from exc
    if not isinstance(jobs_payload, dict):
        raise RuntimeError("OpenClaw cron list output must be a JSON object.")

    matching_ids = _matching_openclaw_job_ids(jobs_payload, binding["scheduled_job"])
    if len(matching_ids) > 1:
        raise ValueError(
            f"Multiple OpenClaw cron jobs matched Twinbox schedule `{job_name}` / `{binding['scheduled_job']}`."
        )

    event_text = _openclaw_system_event_text(binding["scheduled_job"])
    if matching_ids:
        job_id = matching_ids[0]
        run(
            [
                "openclaw",
                "cron",
                "edit",
                job_id,
                "--name",
                binding["platform_name"],
                "--description",
                binding["description"],
                "--cron",
                cron,
                "--tz",
                timezone,
                "--system-event",
                event_text,
            ]
        )
        return {
            "status": "updated",
            "job_id": job_id,
            "job_name": job_name,
            "scheduled_job": binding["scheduled_job"],
            "platform_name": binding["platform_name"],
            "cron": cron,
            "timezone": timezone,
        }

    add_stdout = run(
        [
            "openclaw",
            "cron",
            "add",
            "--json",
            "--name",
            binding["platform_name"],
            "--description",
            binding["description"],
            "--cron",
            cron,
            "--tz",
            timezone,
            "--system-event",
            event_text,
        ]
    )
    job_id = ""
    if add_stdout.strip():
        try:
            add_payload = json.loads(add_stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenClaw cron add output is not valid JSON: {exc.msg}") from exc
        if not isinstance(add_payload, dict):
            raise RuntimeError("OpenClaw cron add output must be a JSON object.")
        job_id = _extract_openclaw_job_id(add_payload)
    return {
        "status": "created",
        "job_id": job_id,
        "job_name": job_name,
        "scheduled_job": binding["scheduled_job"],
        "platform_name": binding["platform_name"],
        "cron": cron,
        "timezone": timezone,
    }


def _platform_sync_payload(
    *,
    job_name: str,
    cron: str,
    timezone: str,
    skill_path: Path | None = None,
) -> dict[str, Any]:
    try:
        result = sync_schedule_to_openclaw(
            job_name=job_name,
            cron=cron,
            timezone=timezone,
            skill_path=skill_path,
        )
        result["message"] = "OpenClaw cron job synced."
        return result
    except (RuntimeError, ValueError) as exc:
        return {
            "status": "error",
            "job_name": job_name,
            "cron": cron,
            "timezone": timezone,
            "message": str(exc),
        }


def load_schedule_config(state_root: Path, skill_path: Path | None = None) -> dict[str, Any]:
    defaults = load_schedule_defaults(skill_path)
    overrides = load_schedule_overrides(state_root)
    override_map = overrides["overrides"]
    schedules: list[dict[str, Any]] = []
    for row in defaults["schedules"]:
        name = row["name"]
        default_cron = row["cron"]
        effective_cron = override_map.get(name, default_cron)
        schedules.append(
            {
                "name": name,
                "default_cron": default_cron,
                "effective_cron": effective_cron,
                "source": "override" if name in override_map else "default",
                "command": row.get("command", ""),
                "description": row.get("description", ""),
            }
        )
    return {"timezone": overrides.get("timezone", DEFAULT_TIMEZONE), "schedules": schedules}


def _known_schedule_names(skill_path: Path | None = None) -> set[str]:
    defaults = load_schedule_defaults(skill_path)
    return {row["name"] for row in defaults["schedules"]}


def update_schedule_override(
    *,
    state_root: Path,
    job_name: str,
    cron: str,
    skill_path: Path | None = None,
) -> dict[str, Any]:
    if job_name not in _known_schedule_names(skill_path):
        raise ValueError(f"Unknown schedule: {job_name}")
    error = validate_cron_expression(cron)
    if error:
        raise ValueError(error)

    payload = load_schedule_overrides(state_root)
    payload["timezone"] = str(payload.get("timezone", DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE)
    payload["overrides"][job_name] = str(cron)
    _write_schedule_overrides(state_root, payload)

    config = load_schedule_config(state_root, skill_path)
    current = next(row for row in config["schedules"] if row["name"] == job_name)
    platform_sync = _platform_sync_payload(
        job_name=job_name,
        cron=current["effective_cron"],
        timezone=config["timezone"],
        skill_path=skill_path,
    )
    return {
        "timezone": config["timezone"],
        "job_name": job_name,
        **current,
        "platform_sync": platform_sync,
        "next_action": (
            "OpenClaw cron job synced."
            if platform_sync.get("status") in {"updated", "created"}
            else "Runtime override saved, but OpenClaw cron sync failed; fix gateway access and retry the same command."
        ),
    }


def reset_schedule_override(
    *,
    state_root: Path,
    job_name: str,
    skill_path: Path | None = None,
) -> dict[str, Any]:
    if job_name not in _known_schedule_names(skill_path):
        raise ValueError(f"Unknown schedule: {job_name}")

    payload = load_schedule_overrides(state_root)
    payload["timezone"] = str(payload.get("timezone", DEFAULT_TIMEZONE) or DEFAULT_TIMEZONE)
    payload["overrides"].pop(job_name, None)
    _write_schedule_overrides(state_root, payload)

    config = load_schedule_config(state_root, skill_path)
    current = next(row for row in config["schedules"] if row["name"] == job_name)
    platform_sync = _platform_sync_payload(
        job_name=job_name,
        cron=current["effective_cron"],
        timezone=config["timezone"],
        skill_path=skill_path,
    )
    return {
        "timezone": config["timezone"],
        "job_name": job_name,
        **current,
        "reset": True,
        "platform_sync": platform_sync,
        "next_action": (
            "OpenClaw cron job synced back to the default schedule."
            if platform_sync.get("status") in {"updated", "created"}
            else "Runtime override reset, but OpenClaw cron sync failed; fix gateway access and retry the same command."
        ),
    }
