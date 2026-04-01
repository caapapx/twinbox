"""Shared Phase-2 host prerequisite bundle: plugin/tools + vendor-safe bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from twinbox_core.host_bridge import (
    bridge_health_check,
    host_bridge_status,
    install_host_bridge,
    remove_host_bridge,
)
from twinbox_core.openclaw_deploy_types import DeployStepResult, OpenClawDeployReport
from twinbox_core.openclaw_json_io import load_openclaw_json


def inspect_openclaw_plugin_tools(openclaw_json: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Best-effort: read openclaw.json and summarize Twinbox plugin + skill entries."""
    loaded_names: list[str] = []
    detail: dict[str, Any] = {}
    try:
        data = load_openclaw_json(openclaw_json)
    except OSError as exc:
        if dry_run:
            return {
                "status": "ok",
                "loaded_names": ["skills.entries.twinbox"],
                "detail": {"note": "dry_run_openclaw_json_not_readable", "error": str(exc)},
            }
        return {
            "status": "failed",
            "loaded_names": [],
            "error": str(exc),
            "detail": {},
        }

    skills = data.get("skills", {})
    entries = skills.get("entries", {}) if isinstance(skills, dict) else {}
    twin_skill = entries.get("twinbox") if isinstance(entries, dict) else None
    skill_ok = isinstance(twin_skill, dict) and twin_skill.get("enabled", True)
    if dry_run and not skill_ok:
        return {
            "status": "ok",
            "loaded_names": ["skills.entries.twinbox"],
            "detail": {"note": "dry_run_merge_not_persisted_to_disk"},
        }
    if skill_ok:
        loaded_names.append("skills.entries.twinbox")

    plugins = data.get("plugins", {})
    plug_entries = plugins.get("entries", {}) if isinstance(plugins, dict) else {}
    if isinstance(plug_entries, dict):
        for key, val in plug_entries.items():
            if not isinstance(val, dict):
                continue
            if not val.get("enabled", True):
                continue
            kid = str(val.get("id", "") or key)
            if "twinbox" in key.lower() or "twinbox" in kid.lower():
                loaded_names.append(kid or key)
                detail[key] = {"id": kid, "enabled": True}
    load_paths = plugins.get("load", {}) if isinstance(plugins, dict) else {}
    paths = load_paths.get("paths", []) if isinstance(load_paths, dict) else []
    if isinstance(paths, list):
        detail["plugin_paths"] = [str(p) for p in paths if str(p).strip()]

    # Treat as ok if twinbox skill is enabled; plugin path may be user-managed.
    status = "ok" if skill_ok else "incomplete"
    return {
        "status": status,
        "loaded_names": sorted(set(loaded_names)),
        "detail": detail,
    }


def run_openclaw_prerequisite_bundle(
    *,
    code_root: Path,
    state_root: Path,
    openclaw_json: Path,
    openclaw_bin: str,
    dry_run: bool,
    skip_bridge: bool,
    twinbox_bin: str | None = None,
) -> dict[str, Any]:
    """After deploy steps (merge json, sync skill, gateway): install bridge + verify."""
    plugin = inspect_openclaw_plugin_tools(openclaw_json, dry_run=dry_run)
    bridge_block: dict[str, Any] = {
        "status": "skipped",
        "reason": "skip_bridge",
    }
    health: dict[str, Any] = {"ok": False, "skipped": True}
    phase2_ready = False

    bridge_status_flat: dict[str, Any] = {}

    if not skip_bridge:
        install_result = install_host_bridge(
            state_root=state_root,
            openclaw_bin=openclaw_bin,
            twinbox_bin=twinbox_bin,
            dry_run=dry_run,
            no_start=False,
        )
        bridge_block = {"install": install_result, "status": install_result.get("status", "unknown")}
        status_obj = host_bridge_status(state_root=state_root, openclaw_bin=openclaw_bin, twinbox_bin=twinbox_bin)
        bridge_status_flat = status_obj
        bridge_block["systemd"] = {
            "timer_enabled": status_obj.get("timer_enabled"),
            "timer_active": status_obj.get("timer_active"),
        }
        if not dry_run:
            health = bridge_health_check(
                code_root=code_root,
                state_root=state_root,
                openclaw_bin=openclaw_bin,
            )
            bridge_block["last_health_check"] = health
        else:
            health = {"ok": True, "skipped": True, "reason": "dry_run"}
            bridge_block["last_health_check"] = health

    plugin_ok = plugin.get("status") == "ok"
    if skip_bridge:
        phase2_ready = plugin_ok  # skip_bridge时只检查plugin，不检查bridge
    else:
        install_st = bridge_block.get("install", {}).get("status")
        install_ok = install_st in ("ok", "dry_run")
        timer_ok = bool(bridge_block.get("systemd", {}).get("timer_enabled")) or dry_run
        health_ok = bool(dry_run or health.get("ok"))
        bridge_ok = install_ok and timer_ok and health_ok
        phase2_ready = bool(plugin_ok and bridge_ok)

    return {
        "plugin_tools": plugin,
        "bridge": bridge_block,
        "bridge_status": bridge_status_flat,
        "skip_bridge": skip_bridge,
        "bridge.timer_enabled": bridge_block.get("systemd", {}).get("timer_enabled") if not skip_bridge else None,
        "bridge.timer_active": bridge_block.get("systemd", {}).get("timer_active") if not skip_bridge else None,
        "bridge.last_health_check": bridge_block.get("last_health_check") if not skip_bridge else None,
        "bridge.twinbox_bin": bridge_block.get("install", {}).get("twinbox_bin") if not skip_bridge else None,
        "bridge.openclaw_bin": openclaw_bin,
        "phase2_ready": phase2_ready,
    }


def append_prereq_to_deploy_report(report: OpenClawDeployReport, prereq: dict[str, Any]) -> None:
    """Attach machine-readable prerequisite summary to deploy report steps."""
    skip = bool(prereq.get("skip_bridge"))
    ready = bool(prereq.get("phase2_ready"))
    step_status = "skipped" if skip else ("ok" if ready else "failed")
    report.steps.append(
        DeployStepResult(
            id="openclaw_prerequisite_bundle",
            status=step_status,
            message="phase2_ready=%s skip_bridge=%s" % (prereq.get("phase2_ready"), skip),
            detail=prereq,
        )
    )
    if not skip and not ready:
        report.ok = False


def rollback_bridge_for_openclaw(
    *,
    state_root: Path,
    dry_run: bool,
) -> dict[str, Any]:
    return remove_host_bridge(state_root=state_root, dry_run=dry_run)
