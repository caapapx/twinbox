"""Host-side OpenClaw wiring: roots init, SKILL sync, openclaw.json merge, gateway restart.

See docs/ref/openclaw-deploy-model.md — this module automates *宿主态* steps only;
onboarding remains conversational (twinbox onboarding …).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .bundled_himalaya import bundled_linux_himalaya_tgz, try_materialize_bundled_himalaya
from .env_writer import load_env_file
from .mail_env_contract import missing_required_mail_values
from .openclaw_config_merge import (
    apply_openclaw_plugin_vendor_cwd,
    deep_merge_openclaw,
    merge_twinbox_openclaw_entry,
    remove_twinbox_skill_entry_from_openclaw,
)
from .openclaw_json_io import (
    atomic_write_json,
    default_openclaw_fragment_path,
    load_openclaw_json,
    load_openclaw_json_with_file_ops,
)
from .openclaw_deploy_runtime import (
    LocalFileOps,
    OpenClawDeployRuntime,
    build_runtime,
)
from .paths import PathResolutionError, config_dir, resolve_code_root, resolve_state_root


def _skill_canonical_path(state_root: Path) -> Path:
    """Deploy writes repo ``SKILL.md`` here; OpenClaw entry symlinks or copies from this file."""
    return (state_root / "SKILL.md").resolve()


@dataclass
class DeployStepResult:
    id: str
    status: str  # ok | skipped | failed | dry_run
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class OpenClawDeployReport:
    ok: bool
    steps: list[DeployStepResult] = field(default_factory=list)
    code_root: str = ""
    openclaw_home: str = ""
    state_root: str = ""
    skill_dest: str = ""
    skill_canonical_dest: str = ""
    openclaw_json: str = ""
    deploy_host_system: str = ""
    deploy_host_machine: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "code_root": self.code_root,
            "openclaw_home": self.openclaw_home,
            "state_root": self.state_root,
            "skill_dest": self.skill_dest,
            "skill_canonical_dest": self.skill_canonical_dest,
            "openclaw_json": self.openclaw_json,
            "deploy_host_system": self.deploy_host_system,
            "deploy_host_machine": self.deploy_host_machine,
            "steps": [
                {
                    "id": s.id,
                    "status": s.status,
                    "message": s.message,
                    "detail": s.detail,
                }
                for s in self.steps
            ],
        }


@dataclass(frozen=True)
class _DeployContext:
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
class _RollbackContext:
    openclaw_home: Path
    openclaw_json: Path
    skill_dir: Path
    config_path: Path
    dry_run: bool
    restart_gateway: bool
    remove_config: bool
    openclaw_bin: str


def _append_step(
    report: OpenClawDeployReport,
    step_id: str,
    status: str,
    message: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    report.steps.append(
        DeployStepResult(step_id, status, message, detail or {})
    )


def _fail_step(
    report: OpenClawDeployReport,
    step_id: str,
    message: str,
    detail: dict[str, Any] | None = None,
) -> bool:
    report.ok = False
    _append_step(report, step_id, "failed", message, detail)
    return False


def _bootstrap_roots_step(
    ctx: _DeployContext,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
) -> bool:
    if not runtime.file_ops.is_file(ctx.init_script):
        return _fail_step(
            report,
            "bootstrap_init_script",
            f"Missing {ctx.init_script}",
        )

    if ctx.dry_run:
        _append_step(
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
        return _fail_step(report, "bootstrap_roots", str(exc))

    if proc.returncode != 0:
        return _fail_step(
            report,
            "bootstrap_roots",
            "install_openclaw_twinbox_init.sh exited non-zero",
            {
                "returncode": proc.returncode,
                "stderr": (proc.stderr or "")[-4000:],
            },
        )

    _append_step(
        report,
        "bootstrap_roots",
        "ok",
        "Wrote code-root / state-root",
        {"stdout_tail": (proc.stdout or "")[-2000:]},
    )
    return True


def _merge_openclaw_json_step(
    ctx: _DeployContext,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
    *,
    dotenv: dict[str, str],
    missing_required: list[str],
) -> bool:
    try:
        existing = load_openclaw_json_with_file_ops(runtime.file_ops, ctx.openclaw_json)
    except ValueError as exc:
        return _fail_step(report, "merge_openclaw_json", str(exc))

    base = existing
    frag_resolved: Path | None = None
    frag_explicit = ctx.fragment_path is not None

    if ctx.no_fragment:
        _append_step(report, "merge_openclaw_fragment", "skipped", "--no-fragment")
    elif ctx.fragment_path is not None:
        frag_resolved = ctx.fragment_path.expanduser()
        if not runtime.file_ops.is_file(frag_resolved):
            return _fail_step(
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
            return _fail_step(report, "merge_openclaw_fragment", str(exc))
        base = deep_merge_openclaw(existing, fragment_data)
        _append_step(
            report,
            "merge_openclaw_fragment",
            "dry_run" if ctx.dry_run else "ok",
            f"Deep-merged fragment from {frag_resolved}",
            {"path": str(frag_resolved), "explicit": frag_explicit},
        )
    elif not ctx.no_fragment:
        _append_step(
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
        _append_step(
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
        return _fail_step(report, "merge_openclaw_json", str(exc))

    message = "Merged skills.entries.twinbox"
    if ctx.sync_env_from_dotenv and missing_required:
        message += (
            f"; warning: state .env missing keys: {', '.join(missing_required)}"
        )
    _append_step(
        report,
        "merge_openclaw_json",
        "ok",
        message,
        {"missing_required_env_in_dotenv": missing_required},
    )
    return True


def _sync_skill_md_step(
    ctx: _DeployContext,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
) -> bool:
    if not runtime.file_ops.is_file(ctx.skill_src):
        return _fail_step(report, "sync_skill_md", f"Missing {ctx.skill_src}")

    canonical = _skill_canonical_path(ctx.state_root)

    if ctx.dry_run:
        _append_step(
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
        return _fail_step(report, "sync_skill_md", str(exc))

    msg = f"Canonical {canonical}; OpenClaw skill {mode}"
    detail: dict[str, Any] = {
        "mode": mode,
        "canonical": str(canonical),
        "openclaw_skill": str(ctx.skill_dest),
    }
    if extra:
        detail["symlink_error"] = extra
    _append_step(report, "sync_skill_md", "ok", msg, detail)
    return True


def _ensure_himalaya_step(ctx: _DeployContext, report: OpenClawDeployReport) -> bool:
    """Detect host OS/CPU; ensure ``himalaya`` exists for mailbox preflight (best-effort).

    Does not fail deploy on unsupported platforms; records ``skipped`` with guidance.
    """
    system = platform.system()
    machine = platform.machine()
    detail: dict[str, Any] = {"system": system, "machine": machine}
    runtime_bin = ctx.state_root / "runtime" / "bin" / "himalaya"

    path_hit = shutil.which("himalaya")
    if path_hit:
        detail["mode"] = "path"
        detail["himalaya"] = path_hit
        _append_step(
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
        _append_step(
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
        _append_step(
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
        _append_step(
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
        return _fail_step(
            report,
            "ensure_himalaya",
            f"Bundled himalaya extract failed: {exc}",
            detail,
        )

    if dest is not None and dest.exists() and os.access(dest, os.X_OK):
        detail["mode"] = "extracted_bundled"
        detail["himalaya"] = str(dest)
        detail["bundle"] = str(bundle)
        _append_step(
            report,
            "ensure_himalaya",
            "ok",
            f"Extracted bundled himalaya to {dest}",
            detail,
        )
        return True

    return _fail_step(
        report,
        "ensure_himalaya",
        "Bundled himalaya extract produced no usable binary",
        detail,
    )


def _gateway_restart_step(
    *,
    restart_gateway: bool,
    dry_run: bool,
    openclaw_bin: str,
    cwd: Path,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
) -> bool:
    if not restart_gateway:
        _append_step(report, "gateway_restart", "skipped", "--no-restart")
        return True

    if dry_run:
        _append_step(
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
        return _fail_step(report, "gateway_restart", str(exc))

    if proc.returncode != 0:
        return _fail_step(
            report,
            "gateway_restart",
            f"{openclaw_bin} gateway restart failed",
            {
                "returncode": proc.returncode,
                "stderr": (proc.stderr or "")[-4000:],
            },
        )

    _append_step(
        report,
        "gateway_restart",
        "ok",
        "Gateway restart issued",
        {"stdout_tail": (proc.stdout or "")[-2000:]},
    )
    return True


def _strip_openclaw_json_step(
    ctx: _RollbackContext,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
) -> bool:
    try:
        existing = load_openclaw_json_with_file_ops(runtime.file_ops, ctx.openclaw_json)
    except ValueError as exc:
        return _fail_step(report, "strip_openclaw_json", str(exc))

    stripped, had_entry = remove_twinbox_skill_entry_from_openclaw(existing)

    if ctx.dry_run:
        _append_step(
            report,
            "strip_openclaw_json",
            "dry_run",
            f"Would remove skills.entries.twinbox from {ctx.openclaw_json}",
            {"had_twinbox_entry": had_entry},
        )
        return True

    if not had_entry:
        _append_step(
            report,
            "strip_openclaw_json",
            "skipped",
            "No skills.entries.twinbox present",
        )
        return True

    try:
        runtime.file_ops.write_json_atomic(ctx.openclaw_json, stripped)
    except OSError as exc:
        return _fail_step(report, "strip_openclaw_json", str(exc))

    _append_step(
        report,
        "strip_openclaw_json",
        "ok",
        "Removed skills.entries.twinbox",
    )
    return True


def _remove_skill_dir_step(
    ctx: _RollbackContext,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
) -> bool:
    if ctx.dry_run:
        _append_step(
            report,
            "remove_skill_dir",
            "dry_run",
            f"Would remove directory {ctx.skill_dir} if present",
            {"exists": runtime.file_ops.is_dir(ctx.skill_dir)},
        )
        return True

    if not runtime.file_ops.is_dir(ctx.skill_dir):
        _append_step(
            report,
            "remove_skill_dir",
            "skipped",
            "Skill directory not present",
        )
        return True

    try:
        runtime.file_ops.remove_tree(ctx.skill_dir)
    except OSError as exc:
        return _fail_step(report, "remove_skill_dir", str(exc))

    _append_step(report, "remove_skill_dir", "ok", f"Removed {ctx.skill_dir}")
    return True


def _remove_twinbox_config_step(
    ctx: _RollbackContext,
    report: OpenClawDeployReport,
    runtime: OpenClawDeployRuntime,
) -> bool:
    if ctx.dry_run:
        _append_step(
            report,
            "remove_twinbox_config",
            "dry_run",
            (
                f"Would remove {ctx.config_path}"
                if ctx.remove_config
                else "Skipped (--remove-config not set)"
            ),
            {
                "remove_config": ctx.remove_config,
                "exists": runtime.file_ops.is_dir(ctx.config_path),
            },
        )
        return True

    if not ctx.remove_config:
        _append_step(
            report,
            "remove_twinbox_config",
            "skipped",
            "Preserved ~/.config/twinbox (pass --remove-config to delete)",
        )
        return True

    if not runtime.file_ops.is_dir(ctx.config_path):
        _append_step(
            report,
            "remove_twinbox_config",
            "skipped",
            "Config directory not present",
        )
        return True

    try:
        runtime.file_ops.remove_tree(ctx.config_path)
    except OSError as exc:
        return _fail_step(report, "remove_twinbox_config", str(exc))

    _append_step(
        report,
        "remove_twinbox_config",
        "ok",
        f"Removed {ctx.config_path}",
    )
    return True


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
        _append_step(report, "resolve_code_root", "failed", str(exc))
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
    bootstrap_ctx = _DeployContext(
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

    if not _bootstrap_roots_step(bootstrap_ctx, report, runtime):
        return report

    try:
        state_root = resolve_state_root(default_state_root)
    except PathResolutionError as exc:
        if dry_run:
            state_root = default_state_root
        else:
            report.ok = False
            _append_step(report, "resolve_state_root", "failed", str(exc))
            return report

    ctx = _DeployContext(
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
    report.skill_canonical_dest = str(_skill_canonical_path(ctx.state_root))

    dotenv = load_env_file(ctx.state_root / ".env") if ctx.sync_env_from_dotenv else {}
    missing_required = (
        missing_required_mail_values(dotenv) if ctx.sync_env_from_dotenv else []
    )
    if ctx.strict and ctx.sync_env_from_dotenv and missing_required:
        _fail_step(
            report,
            "merge_openclaw_json",
            "--strict: state root .env missing required keys for OpenClaw skill: "
            + ", ".join(missing_required),
            {"missing_required_env_in_dotenv": missing_required},
        )
        return report

    if not _merge_openclaw_json_step(
        ctx,
        report,
        runtime,
        dotenv=dotenv,
        missing_required=missing_required,
    ):
        return report
    if not _ensure_himalaya_step(ctx, report):
        return report
    if not _sync_skill_md_step(ctx, report, runtime):
        return report
    _gateway_restart_step(
        restart_gateway=ctx.restart_gateway,
        dry_run=ctx.dry_run,
        openclaw_bin=ctx.openclaw_bin,
        cwd=ctx.code_root,
        report=report,
        runtime=runtime,
    )
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
    optionally removes ``~/.config/twinbox/`` (code-root / state-root pointers).

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
    ctx = _RollbackContext(
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

    if not _strip_openclaw_json_step(ctx, report, runtime):
        return report
    if not _remove_skill_dir_step(ctx, report, runtime):
        return report
    if not _remove_twinbox_config_step(ctx, report, runtime):
        return report
    _gateway_restart_step(
        restart_gateway=ctx.restart_gateway,
        dry_run=ctx.dry_run,
        openclaw_bin=ctx.openclaw_bin,
        cwd=resolved_code_root or Path.home(),
        report=report,
        runtime=runtime,
    )
    return report
