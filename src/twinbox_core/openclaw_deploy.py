"""Host-side OpenClaw wiring: roots init, SKILL sync, openclaw.json merge, gateway restart.

See docs/ref/openclaw-deploy-model.md — this module automates *宿主态* steps only;
onboarding remains conversational (twinbox onboarding …).
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Callable

from .env_writer import load_env_file
from .mail_env_contract import missing_required_mail_values
from .twinbox_config import config_path_for_state_root
from .openclaw_config_merge import (
    apply_openclaw_plugin_vendor_cwd,
    deep_merge_openclaw,
    merge_twinbox_openclaw_entry,
    remove_twinbox_skill_entry_from_openclaw,
)
from .openclaw_deploy_runtime import OpenClawDeployRuntime, build_runtime
from .openclaw_deploy_steps import (
    DeployContext,
    RollbackContext,
    append_step,
    bootstrap_roots_step,
    fail_step,
    ensure_himalaya_step,
    gateway_restart_step,
    merge_openclaw_json_step,
    remove_skill_dir_step,
    remove_twinbox_config_step,
    skill_canonical_path,
    strip_openclaw_json_step,
    sync_skill_md_step,
)
from .openclaw_deploy_types import DeployStepResult, OpenClawDeployReport
from .openclaw_host_prereq import append_prereq_to_deploy_report, rollback_bridge_for_openclaw, run_openclaw_prerequisite_bundle
from .openclaw_json_io import load_openclaw_json
from .daemon.lifecycle import attempt_daemon_start
from .paths import PathResolutionError, config_dir, resolve_code_root, resolve_state_root

__all__ = [
    "DeployStepResult",
    "OpenClawDeployReport",
    "apply_openclaw_plugin_vendor_cwd",
    "deep_merge_openclaw",
    "load_openclaw_json",
    "merge_twinbox_openclaw_entry",
    "remove_twinbox_skill_entry_from_openclaw",
    "run_openclaw_deploy",
    "run_openclaw_rollback",
]


def run_openclaw_deploy(
    *,
    code_root: Path | None = None,
    openclaw_home: Path | None = None,
    dry_run: bool = False,
    restart_gateway: bool = True,
    sync_env_from_dotenv: bool = True,
    strict: bool = False,
    fragment_path: Path | None = None,
    no_fragment: bool = False,
    openclaw_bin: str = "openclaw",
    skip_bridge: bool = False,
    twinbox_bin: str | None = None,
    start_daemon: bool = True,
    run_subprocess: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    runtime: OpenClawDeployRuntime | None = None,
) -> OpenClawDeployReport:
    """Wire Twinbox into OpenClaw on the current host.

    Steps: roots init script → resolve state root → optional env merge into
    ~/.openclaw/openclaw.json → OS-aware himalaya check/extract → copy SKILL.md to
    state root → gateway restart.
    """
    report = OpenClawDeployReport(ok=True, steps=[])
    report.deploy_host_system = platform.system()
    report.deploy_host_machine = platform.machine()
    runtime = runtime or build_runtime(run_subprocess)

    try:
        resolved_code_root = resolve_code_root(code_root or Path.cwd())
    except PathResolutionError as exc:
        report.ok = False
        append_step(report, "resolve_code_root", "failed", str(exc))
        return report

    resolved_openclaw_home = (openclaw_home or Path.home() / ".openclaw").expanduser()
    report.code_root = str(resolved_code_root)
    report.openclaw_home = str(resolved_openclaw_home)
    report.openclaw_json = str(resolved_openclaw_home / "openclaw.json")
    report.skill_dest = str(
        resolved_openclaw_home / "skills" / "twinbox" / "SKILL.md"
    )

    default_state_root = Path(
        os.environ.get("TWINBOX_STATE_ROOT", str(Path.home() / ".twinbox"))
    ).expanduser()
    bootstrap_ctx = DeployContext(
        code_root=resolved_code_root,
        openclaw_home=resolved_openclaw_home,
        openclaw_json=resolved_openclaw_home / "openclaw.json",
        state_root=default_state_root,
        skill_src=resolved_code_root / "SKILL.md",
        skill_dest=resolved_openclaw_home / "skills" / "twinbox" / "SKILL.md",
        init_script=resolved_code_root / "scripts" / "install_openclaw_twinbox_init.sh",
        dry_run=dry_run,
        restart_gateway=restart_gateway,
        sync_env_from_dotenv=sync_env_from_dotenv,
        strict=strict,
        fragment_path=fragment_path,
        no_fragment=no_fragment,
        openclaw_bin=openclaw_bin,
    )

    if not bootstrap_roots_step(bootstrap_ctx, report, runtime):
        return report

    try:
        state_root = resolve_state_root(default_state_root)
    except PathResolutionError as exc:
        if dry_run:
            state_root = default_state_root
        else:
            report.ok = False
            append_step(report, "resolve_state_root", "failed", str(exc))
            return report

    ctx = DeployContext(
        code_root=resolved_code_root,
        openclaw_home=resolved_openclaw_home,
        openclaw_json=resolved_openclaw_home / "openclaw.json",
        state_root=state_root,
        skill_src=resolved_code_root / "SKILL.md",
        skill_dest=resolved_openclaw_home / "skills" / "twinbox" / "SKILL.md",
        init_script=resolved_code_root / "scripts" / "install_openclaw_twinbox_init.sh",
        dry_run=dry_run,
        restart_gateway=restart_gateway,
        sync_env_from_dotenv=sync_env_from_dotenv,
        strict=strict,
        fragment_path=fragment_path,
        no_fragment=no_fragment,
        openclaw_bin=openclaw_bin,
    )
    report.state_root = str(ctx.state_root)
    report.skill_canonical_dest = str(skill_canonical_path(ctx.state_root))

    dotenv = load_env_file(config_path_for_state_root(ctx.state_root)) if ctx.sync_env_from_dotenv else {}
    missing_required = (
        missing_required_mail_values(dotenv) if ctx.sync_env_from_dotenv else []
    )
    if ctx.strict and ctx.sync_env_from_dotenv and missing_required:
        fail_step(
            report,
            "merge_openclaw_json",
            "--strict: state root twinbox.json (or legacy .env) missing required keys for OpenClaw skill: "
            + ", ".join(missing_required),
            {"missing_required_env_in_dotenv": missing_required},
        )
        return report

    if not merge_openclaw_json_step(
        ctx,
        report,
        runtime,
        dotenv=dotenv,
        missing_required=missing_required,
    ):
        return report
    if not ensure_himalaya_step(ctx, report):
        return report
    if not sync_skill_md_step(ctx, report, runtime):
        return report
    gateway_restart_step(
        restart_gateway=ctx.restart_gateway,
        dry_run=ctx.dry_run,
        openclaw_bin=ctx.openclaw_bin,
        cwd=ctx.code_root,
        report=report,
        runtime=runtime,
    )
    if report.ok:
        prereq = run_openclaw_prerequisite_bundle(
            code_root=resolved_code_root,
            state_root=ctx.state_root,
            openclaw_json=ctx.openclaw_json,
            openclaw_bin=openclaw_bin,
            dry_run=dry_run,
            skip_bridge=skip_bridge,
            twinbox_bin=twinbox_bin,
        )
        pt = prereq.get("plugin_tools")
        report.plugin_tools = pt if isinstance(pt, dict) else {}
        br = prereq.get("bridge")
        report.bridge = br if isinstance(br, dict) else {}
        report.phase2_ready = bool(prereq.get("phase2_ready"))
        append_prereq_to_deploy_report(report, prereq)

    if report.ok and not dry_run and start_daemon:
        outcome, msg = attempt_daemon_start(ctx.state_root)
        if outcome == "started":
            append_step(report, "daemon_start", "ok", msg)
        elif outcome == "skipped_already_running":
            append_step(report, "daemon_start", "skipped", msg)
        else:
            append_step(report, "daemon_start", "failed", msg)
    return report


def run_openclaw_rollback(
    *,
    code_root: Path | None = None,
    openclaw_home: Path | None = None,
    dry_run: bool = False,
    restart_gateway: bool = True,
    remove_config: bool = False,
    openclaw_bin: str = "openclaw",
    run_subprocess: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    runtime: OpenClawDeployRuntime | None = None,
) -> OpenClawDeployReport:
    """Undo host wiring done by :func:`run_openclaw_deploy` (narrow scope).

    Removes ``skills.entries.twinbox``, deletes ``~/.openclaw/skills/twinbox/``,
    optionally removes ``~/.twinbox`` pointer files (``code-root``, ``state-root``,
    ``canonical-root``, bridge env) and legacy ``~/.config/twinbox/`` if present.

    Does **not** remove ``~/.twinbox`` (mail state), OpenClaw plugins, cron,
    systemd bridge, or ``uninstall_openclaw_twinbox.sh`` scope — use that script
    for a full teardown.
    """
    report = OpenClawDeployReport(ok=True, steps=[])
    runtime = runtime or build_runtime(run_subprocess)

    try:
        resolved_code_root = resolve_code_root(code_root or Path.cwd())
        report.code_root = str(resolved_code_root)
    except PathResolutionError:
        resolved_code_root = None
        report.code_root = ""

    default_state_root = Path(
        os.environ.get("TWINBOX_STATE_ROOT", str(Path.home() / ".twinbox"))
    ).expanduser()
    try:
        report.state_root = str(resolve_state_root(default_state_root))
    except PathResolutionError:
        report.state_root = str(default_state_root)

    resolved_openclaw_home = (openclaw_home or Path.home() / ".openclaw").expanduser()
    ctx = RollbackContext(
        openclaw_home=resolved_openclaw_home,
        openclaw_json=resolved_openclaw_home / "openclaw.json",
        skill_dir=resolved_openclaw_home / "skills" / "twinbox",
        config_path=config_dir(),
        dry_run=dry_run,
        restart_gateway=restart_gateway,
        remove_config=remove_config,
        openclaw_bin=openclaw_bin,
    )
    report.openclaw_home = str(ctx.openclaw_home)
    report.openclaw_json = str(ctx.openclaw_json)
    report.skill_dest = str(ctx.skill_dir / "SKILL.md")

    try:
        sr = resolve_state_root(default_state_root)
    except PathResolutionError:
        sr = default_state_root
    bridge_rb = rollback_bridge_for_openclaw(state_root=sr, dry_run=dry_run)
    append_step(
        report,
        "bridge_remove",
        "ok" if bridge_rb.get("status") == "ok" else "skipped",
        str(bridge_rb.get("status", "")),
        bridge_rb,
    )

    if not strip_openclaw_json_step(ctx, report, runtime):
        return report
    if not remove_skill_dir_step(ctx, report, runtime):
        return report
    if not remove_twinbox_config_step(ctx, report, runtime):
        return report
    gateway_restart_step(
        restart_gateway=ctx.restart_gateway,
        dry_run=ctx.dry_run,
        openclaw_bin=ctx.openclaw_bin,
        cwd=resolved_code_root or Path.home(),
        report=report,
        runtime=runtime,
    )
    return report
