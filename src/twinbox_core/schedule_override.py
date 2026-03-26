"""Runtime schedule override helpers layered on top of SKILL.md defaults."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

DEFAULT_TIMEZONE = "Asia/Shanghai"


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
    return {
        "timezone": config["timezone"],
        "job_name": job_name,
        **current,
        "next_action": "OpenClaw schedule metadata is declaration-only here; redeploy or refresh the hosted skill registration manually.",
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
    return {
        "timezone": config["timezone"],
        "job_name": job_name,
        **current,
        "reset": True,
        "next_action": "If OpenClaw is hosting this skill, manually redeploy or refresh schedule registration to apply the default cron.",
    }
