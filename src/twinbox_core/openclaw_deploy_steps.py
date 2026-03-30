"""Individual OpenClaw deploy/rollback steps (orchestration lives in ``openclaw_deploy``)."""

from __future__ import annotations

import os
import platform
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bundled_himalaya import bundled_linux_himalaya_tgz, try_materialize_bundled_himalaya
from .openclaw_config_merge import (
    apply_openclaw_plugin_vendor_cwd,
    deep_merge_openclaw,
    merge_twinbox_openclaw_entry,
    remove_twinbox_skill_entry_from_openclaw,
)
from .openclaw_json_io import (
    default_openclaw_fragment_path,
    load_openclaw_json_with_file_ops,
)
from .host_bridge import bridge_env_path, legacy_bridge_env_path
from .openclaw_deploy_runtime import OpenClawDeployRuntime
from .openclaw_deploy_types import DeployStepResult, OpenClawDeployReport
from .paths import legacy_config_dir


def skill_canonical_path(state_root: Path) -> Path:
    """Deploy writes repo ``SKILL.md`` here; OpenClaw entry symlinks or copies from this file."""
    return (state_root / "SKILL.md").resolve()


@dataclass(frozen=True)
class DeployContext:
    code_root: Path
    openclaw_home: Path
    openclaw_json: Path
    state_root: Path
    skill_src: Path
    skill_dest: Path
    init_script: Path
    dry_run: bool
    restart_gateway: bool
    sync_env_from_dotenv: bool
    strict: bool
    fragment_path: Path | None
    no_fragment: bool
    openclaw_bin: str


@dataclass(frozen=True)
class RollbackContext:
    openclaw_home: Path
    openclaw_json: Path
    skill_dir: Path
    config_path: Path
    dry_run: bool
    restart_gateway: bool
    remove_config: bool
    openclaw_bin: str


def append_step(
    report: OpenClawDeployReport,
    step_id: str,
    status: str,
    message: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    report.steps.append(
        DeployStepResult(step_id, status, message, detail or {})
    )


def fail_step(
    report: OpenClawDeployReport,
    step_id: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> bool:
    report.ok = False
    append_step(report, step_id, "failed", message, detail)
    return False


def bootstrap_roots_step(
    ctx: DeployContext,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
) -> bool:
    if not runtime.file_ops.is_file(ctx.init_script):
        return fail_step(
            report,
            "bootstrap_init_script",
            f"Missing {ctx.init_script}",
        )

    if ctx.dry_run:
        append_step(
            report,
            "bootstrap_roots",
            "dry_run",
            f"Would run: bash {ctx.init_script}",
            {"script": str(ctx.init_script)},
        )
        return True

    try:
        proc = runtime.command_runner.run(
            ["bash", str(ctx.init_script)],
            cwd=ctx.code_root,
        )
    except OSError as exc:
        return fail_step(report, "bootstrap_roots", str(exc))

    if proc.returncode != 0:
        return fail_step(
            report,
            "bootstrap_roots",
            "install_openclaw_twinbox_init.sh exited non-zero",
            {
                "returncode": proc.returncode,
                "stderr": (proc.stderr or "")[-4000:],
            },
        )

    append_step(
        report,
        "bootstrap_roots",
        "ok",
        "Wrote code-root / state-root",
        {"stdout_tail": (proc.stdout or "")[-2000:]},
    )
    return True


def merge_openclaw_json_step(
    ctx: DeployContext,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
    *,
    dotenv: dict[str, str],
    missing_required: list[str],
) -> bool:
    try:
        existing = load_openclaw_json_with_file_ops(runtime.file_ops, ctx.openclaw_json)
    except ValueError as exc:
        return fail_step(report, "merge_openclaw_json", str(exc))

    base = existing
    frag_resolved: Path | None = None
    frag_explicit = ctx.fragment_path is not None

    if ctx.no_fragment:
        append_step(report, "merge_openclaw_fragment", "skipped", "--no-fragment")
    elif ctx.fragment_path is not None:
        frag_resolved = ctx.fragment_path.expanduser()
        if not runtime.file_ops.is_file(frag_resolved):
            return fail_step(
                report,
                "merge_openclaw_fragment",
                f"Fragment file not found: {frag_resolved}",
            )
    else:
        candidate = default_openclaw_fragment_path(ctx.code_root)
        if runtime.file_ops.is_file(candidate):
            frag_resolved = candidate

    if frag_resolved is not None:
        try:
            fragment_data = load_openclaw_json_with_file_ops(runtime.file_ops, frag_resolved)
        except ValueError as exc:
            return fail_step(report, "merge_openclaw_fragment", str(exc))
        base = deep_merge_openclaw(existing, fragment_data)
        append_step(
            report,
            "merge_openclaw_fragment",
            "dry_run" if ctx.dry_run else "ok",
            f"Deep-merged fragment from {frag_resolved}",
            {"path": str(frag_resolved), "explicit": frag_explicit},
        )
    elif not ctx.no_fragment:
        append_step(
            report,
            "merge_openclaw_fragment",
            "skipped",
            f"No {default_openclaw_fragment_path(ctx.code_root)} (optional)",
        )

    merged = merge_twinbox_openclaw_entry(
        base,
        dotenv=dotenv,
        sync_env_from_dotenv=ctx.sync_env_from_dotenv,
    )
    merged = apply_openclaw_plugin_vendor_cwd(merged, ctx.state_root)

    if ctx.dry_run:
        append_step(
            report,
            "merge_openclaw_json",
            "dry_run",
            f"Would write {ctx.openclaw_json}",
            {
                "sync_env_from_dotenv": ctx.sync_env_from_dotenv,
                "missing_required_env_in_dotenv": missing_required,
            },
        )
        return True

    try:
        runtime.file_ops.write_json_atomic(ctx.openclaw_json, merged)
    except OSError as exc:
        return fail_step(report, "merge_openclaw_json", str(exc))

    message = "Merged skills.entries.twinbox"
    if ctx.sync_env_from_dotenv and missing_required:
        message += (
            f"; warning: state .env missing keys: {', '.join(missing_required)}"
        )
    append_step(
        report,
        "merge_openclaw_json",
        "ok",
        message,
        {"missing_required_env_in_dotenv": missing_required},
    )
    return True


def sync_skill_md_step(
    ctx: DeployContext,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
) -> bool:
    if not runtime.file_ops.is_file(ctx.skill_src):
        return fail_step(report, "sync_skill_md", f"Missing {ctx.skill_src}")

    canonical = skill_canonical_path(ctx.state_root)

    if ctx.dry_run:
        append_step(
            report,
            "sync_skill_md",
            "dry_run",
            f"Would copy {ctx.skill_src} -> {canonical}; then symlink {ctx.skill_dest} -> "
            f"{canonical} (or copy if symlink unsupported)",
            {"canonical": str(canonical), "openclaw_skill": str(ctx.skill_dest)},
        )
        return True

    try:
        runtime.file_ops.mkdir(canonical.parent, parents=True, exist_ok=True)
        runtime.file_ops.copy_file(ctx.skill_src, canonical)
        runtime.file_ops.unlink(ctx.skill_dest)
        try:
            runtime.file_ops.symlink(canonical, ctx.skill_dest)
            mode = "symlink"
            extra = ""
        except OSError as exc:
            runtime.file_ops.copy_file(canonical, ctx.skill_dest)
            mode = "copy_fallback"
            extra = str(exc)
    except OSError as exc:
        return fail_step(report, "sync_skill_md", str(exc))

    msg = f"Canonical {canonical}; OpenClaw skill {mode}"
    detail: dict[str, Any] = {
        "mode": mode,
        "canonical": str(canonical),
        "openclaw_skill": str(ctx.skill_dest),
    }
    if extra:
        detail["symlink_error"] = extra
    append_step(report, "sync_skill_md", "ok", msg, detail)
    return True


def ensure_himalaya_step(ctx: DeployContext, report: OpenClawDeployReport) -> bool:
    """Detect host OS/CPU; ensure ``himalaya`` exists for mailbox preflight (best-effort)."""
    system = platform.system()
    machine = platform.machine()
    detail: dict[str, Any] = {"system": system, "machine": machine}
    runtime_bin = ctx.state_root / "runtime" / "bin" / "himalaya"

    path_hit = shutil.which("himalaya")
    if path_hit:
        detail["mode"] = "path"
        detail["himalaya"] = path_hit
        append_step(
            report,
            "ensure_himalaya",
            "ok",
            f"himalaya on PATH ({path_hit})",
            detail,
        )
        return True

    if runtime_bin.exists() and os.access(runtime_bin, os.X_OK):
        detail["mode"] = "state_runtime_bin"
        detail["himalaya"] = str(runtime_bin)
        append_step(
            report,
            "ensure_himalaya",
            "ok",
            f"himalaya already at {runtime_bin}",
            detail,
        )
        return True

    bundle = bundled_linux_himalaya_tgz()
    if bundle is None:
        detail["mode"] = "skipped"
        detail["reason"] = (
            "No bundled himalaya for this host (shipped: Linux x86_64, Linux aarch64 only)"
        )
        append_step(
            report,
            "ensure_himalaya",
            "skipped",
            f"No himalaya in PATH or {runtime_bin}; install the CLI for {system}/{machine} "
            "or copy a binary to runtime/bin/himalaya",
            detail,
        )
        return True

    if ctx.dry_run:
        detail["mode"] = "would_extract_bundled"
        detail["bundle"] = str(bundle)
        detail["target"] = str(runtime_bin)
        append_step(
            report,
            "ensure_himalaya",
            "dry_run",
            f"Would extract bundled {bundle.name} -> {runtime_bin}",
            detail,
        )
        return True

    try:
        dest = try_materialize_bundled_himalaya(ctx.state_root)
    except (OSError, RuntimeError, tarfile.TarError) as exc:
        return fail_step(
            report,
            "ensure_himalaya",
            f"Bundled himalaya extract failed: {exc}",
            detail,
        )

    if dest is not None and dest.exists() and os.access(dest, os.X_OK):
        detail["mode"] = "extracted_bundled"
        detail["himalaya"] = str(dest)
        detail["bundle"] = str(bundle)
        append_step(
            report,
            "ensure_himalaya",
            "ok",
            f"Extracted bundled himalaya to {dest}",
            detail,
        )
        return True

    return fail_step(
        report,
        "ensure_himalaya",
        "Bundled himalaya extract produced no usable binary",
        detail,
    )


def gateway_restart_step(
    *,
    restart_gateway: bool,
    dry_run: bool,
    openclaw_bin: str,
    cwd: Path,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
) -> bool:
    if not restart_gateway:
        append_step(report, "gateway_restart", "skipped", "--no-restart")
        return True

    if dry_run:
        append_step(
            report,
            "gateway_restart",
            "dry_run",
            f"Would run: {openclaw_bin} gateway restart",
        )
        return True

    try:
        proc = runtime.command_runner.run(
            [openclaw_bin, "gateway", "restart"],
            cwd=cwd,
        )
    except OSError as exc:
        return fail_step(report, "gateway_restart", str(exc))

    if proc.returncode != 0:
        return fail_step(
            report,
            "gateway_restart",
            f"{openclaw_bin} gateway restart failed",
            {
                "returncode": proc.returncode,
                "stderr": (proc.stderr or "")[-4000:],
            },
        )

    append_step(
        report,
        "gateway_restart",
        "ok",
        "Gateway restart issued",
        {"stdout_tail": (proc.stdout or "")[-2000:]},
    )
    return True


def strip_openclaw_json_step(
    ctx: RollbackContext,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
) -> bool:
    try:
        existing = load_openclaw_json_with_file_ops(runtime.file_ops, ctx.openclaw_json)
    except ValueError as exc:
        return fail_step(report, "strip_openclaw_json", str(exc))

    stripped, had_entry = remove_twinbox_skill_entry_from_openclaw(existing)

    if ctx.dry_run:
        append_step(
            report,
            "strip_openclaw_json",
            "dry_run",
            f"Would remove skills.entries.twinbox from {ctx.openclaw_json}",
            {"had_twinbox_entry": had_entry},
        )
        return True

    if not had_entry:
        append_step(
            report,
            "strip_openclaw_json",
            "skipped",
            "No skills.entries.twinbox present",
        )
        return True

    try:
        runtime.file_ops.write_json_atomic(ctx.openclaw_json, stripped)
    except OSError as exc:
        return fail_step(report, "strip_openclaw_json", str(exc))

    append_step(
        report,
        "strip_openclaw_json",
        "ok",
        "Removed skills.entries.twinbox",
    )
    return True


def remove_skill_dir_step(
    ctx: RollbackContext,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
) -> bool:
    if ctx.dry_run:
        append_step(
            report,
            "remove_skill_dir",
            "dry_run",
            f"Would remove directory {ctx.skill_dir} if present",
            {"exists": runtime.file_ops.is_dir(ctx.skill_dir)},
        )
        return True

    if not runtime.file_ops.is_dir(ctx.skill_dir):
        append_step(
            report,
            "remove_skill_dir",
            "skipped",
            "Skill directory not present",
        )
        return True

    try:
        runtime.file_ops.remove_tree(ctx.skill_dir)
    except OSError as exc:
        return fail_step(report, "remove_skill_dir", str(exc))

    append_step(report, "remove_skill_dir", "ok", f"Removed {ctx.skill_dir}")
    return True


def _twinbox_pointer_files_for_rollback() -> list[Path]:
    """Small pointer files under ``~/.twinbox`` (never remove the whole state tree)."""
    root = Path.home() / ".twinbox"
    return [
        root / "code-root",
        root / "state-root",
        root / "canonical-root",
        bridge_env_path(),
        legacy_bridge_env_path(),
    ]


def remove_twinbox_config_step(
    ctx: RollbackContext,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
) -> bool:
    legacy = legacy_config_dir()
    pointer_files = _twinbox_pointer_files_for_rollback()
    if ctx.dry_run:
        append_step(
            report,
            "remove_twinbox_config",
            "dry_run",
            (
                f"Would remove pointer files + legacy {legacy}"
                if ctx.remove_config
                else "Skipped (--remove-config not set)"
            ),
            {
                "remove_config": ctx.remove_config,
                "pointer_files": [str(p) for p in pointer_files],
                "legacy_dir": str(legacy),
                "legacy_exists": runtime.file_ops.is_dir(legacy),
            },
        )
        return True

    if not ctx.remove_config:
        append_step(
            report,
            "remove_twinbox_config",
            "skipped",
            "Preserved ~/.twinbox pointer files (pass --remove-config to delete)",
        )
        return True

    removed: list[str] = []
    try:
        for p in pointer_files:
            if runtime.file_ops.is_file(p):
                runtime.file_ops.unlink(p)
                removed.append(str(p))
        if runtime.file_ops.is_dir(legacy):
            runtime.file_ops.remove_tree(legacy)
            removed.append(str(legacy))
    except OSError as exc:
        return fail_step(report, "remove_twinbox_config", str(exc))

    if not removed:
        append_step(
            report,
            "remove_twinbox_config",
            "skipped",
            "No pointer files or legacy ~/.config/twinbox dir present",
        )
        return True

    append_step(
        report,
        "remove_twinbox_config",
        "ok",
        f"Removed {', '.join(removed)}",
    )
    return True
