"""Pure OpenClaw ``openclaw.json`` merge helpers (no deploy orchestration)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .mail_env_contract import OPENCLAW_ENV_KEYS


def _deep_copy_json(obj: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(obj))


def deep_merge_openclaw(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge *src* into a copy of *dst*.

    Nested dicts are merged recursively; lists and scalars from *src* replace.
    """
    out = _deep_copy_json(dst)
    for key, val in src.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = deep_merge_openclaw(out[key], val)
        elif isinstance(val, dict):
            out[key] = _deep_copy_json(val)
        elif isinstance(val, list):
            out[key] = list(val)
        else:
            out[key] = val
    return out


def merge_twinbox_openclaw_entry(
    base: dict[str, Any],
    *,
    dotenv: dict[str, str],
    sync_env_from_dotenv: bool,
) -> dict[str, Any]:
    """Return a new config dict with skills.entries.twinbox updated.

    Preserves all other top-level keys and non-twinbox entries.
    When sync_env_from_dotenv is False, only sets enabled=True and leaves env unchanged.
    """
    out = _deep_copy_json(base) if base else {}
    skills = out.setdefault("skills", {})
    if not isinstance(skills, dict):
        skills = {}
        out["skills"] = skills
    entries = skills.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        skills["entries"] = entries

    twin_raw = entries.get("twinbox", {})
    twin: dict[str, Any] = dict(twin_raw) if isinstance(twin_raw, dict) else {}
    twin["enabled"] = True

    if sync_env_from_dotenv:
        env_raw = twin.get("env", {})
        env: dict[str, str] = dict(env_raw) if isinstance(env_raw, dict) else {}
        for key in OPENCLAW_ENV_KEYS:
            val = (dotenv.get(key) or "").strip()
            if val:
                env[key] = val
        twin["env"] = env
    else:
        if "env" not in twin:
            twin["env"] = {}

    entries["twinbox"] = twin
    return out


def remove_twinbox_skill_entry_from_openclaw(
    data: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Return (new_config, had_twinbox_entry).

    Preserves all other keys; only drops ``skills.entries.twinbox``.
    """
    out = _deep_copy_json(data) if data else {}
    skills = out.get("skills")
    if not isinstance(skills, dict):
        return out, False
    entries = skills.get("entries")
    if not isinstance(entries, dict):
        return out, False
    had = "twinbox" in entries
    skills["entries"] = {k: v for k, v in entries.items() if k != "twinbox"}
    out["skills"] = skills
    return out, had


def ensure_twinbox_plugin_config(data: dict[str, Any], state_root: Path) -> dict[str, Any]:
    """Ensure plugins.entries.twinbox-task-tools exists with proper paths."""
    from twinbox_core.vendor_sync import vendor_root
    import shutil

    out = _deep_copy_json(data) if data else {}
    plugins = out.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        plugins = {}
        out["plugins"] = plugins

    load = plugins.setdefault("load", {})
    if not isinstance(load, dict):
        load = {}
        plugins["load"] = load

    paths = load.setdefault("paths", [])
    if not isinstance(paths, list):
        paths = []
        load["paths"] = paths

    vr = vendor_root(state_root)
    plugin_path = str((vr / "integrations" / "openclaw" / "plugin-twinbox-task").resolve())
    if plugin_path not in paths:
        paths.append(plugin_path)

    entries = plugins.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        plugins["entries"] = entries

    if "twinbox-task-tools" not in entries:
        twinbox_bin = shutil.which("twinbox") or "twinbox"
        entries["twinbox-task-tools"] = {
            "enabled": True,
            "config": {
                "cwd": str(vr.resolve()),
                "twinboxBin": twinbox_bin,
            },
        }

    return out


def apply_openclaw_plugin_vendor_cwd(data: dict[str, Any], state_root: Path) -> dict[str, Any]:
    """If ``vendor/twinbox_core`` exists under the shared vendor home, set plugin ``config.cwd`` there.

    OpenClaw plugin entries that reference Twinbox (name or ``twinboxBin``) need ``cwd`` on
    ``PYTHONPATH`` parent (the ``vendor`` directory).
    """
    from twinbox_core.vendor_sync import vendor_root, vendor_twinbox_core_path

    vr = vendor_root(state_root)
    if not (vendor_twinbox_core_path(state_root) / "__init__.py").is_file():
        return data
    cwd_s = str(vr.resolve())
    plugins = data.get("plugins")
    if not isinstance(plugins, dict):
        return data
    entries = plugins.get("entries")
    if not isinstance(entries, dict):
        return data
    for name, ent in entries.items():
        if not isinstance(ent, dict):
            continue
        cfg = ent.get("config")
        if not isinstance(cfg, dict):
            cfg = {}
            ent["config"] = cfg
        if "twinbox" not in name.lower() and "twinboxBin" not in cfg:
            continue
        cfg["cwd"] = cwd_s
        entries[name] = ent
    plugins["entries"] = entries
    data["plugins"] = plugins
    return data
