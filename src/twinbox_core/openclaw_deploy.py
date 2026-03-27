"""Host-side OpenClaw wiring: roots init, SKILL sync, openclaw.json merge, gateway restart.

See docs/ref/openclaw-deploy-model.md — this module automates *宿主态* steps only;
onboarding remains conversational (twinbox onboarding …).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .env_writer import load_env_file
from .paths import PathResolutionError, config_dir, resolve_code_root, resolve_state_root

# Matches SKILL.md metadata.openclaw.requires.env
OPENCLAW_REQUIRED_MAIL_KEYS = (
    "IMAP_HOST",
    "IMAP_PORT",
    "IMAP_LOGIN",
    "IMAP_PASS",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_LOGIN",
    "SMTP_PASS",
    "MAIL_ADDRESS",
)

OPENCLAW_OPTIONAL_MAIL_KEYS = (
    "MAIL_ACCOUNT_NAME",
    "MAIL_DISPLAY_NAME",
    "IMAP_ENCRYPTION",
    "SMTP_ENCRYPTION",
)

OPENCLAW_ENV_KEYS = OPENCLAW_REQUIRED_MAIL_KEYS + OPENCLAW_OPTIONAL_MAIL_KEYS


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
    openclaw_json: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "code_root": self.code_root,
            "openclaw_home": self.openclaw_home,
            "state_root": self.state_root,
            "skill_dest": self.skill_dest,
            "openclaw_json": self.openclaw_json,
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


def default_openclaw_fragment_path(code_root: Path) -> Path:
    return code_root / "openclaw-skill" / "openclaw.fragment.json"


def load_openclaw_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


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


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=".openclaw-", suffix=".json.tmp", text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


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
) -> OpenClawDeployReport:
    """Wire Twinbox into OpenClaw on the current host.

    Steps: roots init script → resolve state root → optional env merge into
    ~/.openclaw/openclaw.json → copy SKILL.md → gateway restart.
    """
    run = run_subprocess or subprocess.run
    report = OpenClawDeployReport(ok=True, steps=[])

    try:
        cr = resolve_code_root(code_root or Path.cwd())
    except PathResolutionError as exc:
        report.ok = False
        report.steps.append(
            DeployStepResult("resolve_code_root", "failed", str(exc))
        )
        return report

    report.code_root = str(cr)
    och = (openclaw_home or Path.home() / ".openclaw").expanduser()
    report.openclaw_home = str(och)
    report.openclaw_json = str(och / "openclaw.json")
    skill_src = cr / "SKILL.md"
    skill_dest = och / "skills" / "twinbox" / "SKILL.md"
    report.skill_dest = str(skill_dest)

    init_script = cr / "scripts" / "install_openclaw_twinbox_init.sh"
    if not init_script.is_file():
        report.ok = False
        report.steps.append(
            DeployStepResult(
                "bootstrap_init_script",
                "failed",
                f"Missing {init_script}",
            )
        )
        return report

    # --- roots init ---
    if dry_run:
        report.steps.append(
            DeployStepResult(
                "bootstrap_roots",
                "dry_run",
                f"Would run: bash {init_script}",
                {"script": str(init_script)},
            )
        )
    else:
        try:
            proc = run(
                ["bash", str(init_script)],
                cwd=str(cr),
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                report.ok = False
                report.steps.append(
                    DeployStepResult(
                        "bootstrap_roots",
                        "failed",
                        "install_openclaw_twinbox_init.sh exited non-zero",
                        {
                            "returncode": proc.returncode,
                            "stderr": (proc.stderr or "")[-4000:],
                        },
                    )
                )
                return report
            report.steps.append(
                DeployStepResult(
                    "bootstrap_roots",
                    "ok",
                    "Wrote code-root / state-root",
                    {"stdout_tail": (proc.stdout or "")[-2000:]},
                )
            )
        except OSError as exc:
            report.ok = False
            report.steps.append(
                DeployStepResult("bootstrap_roots", "failed", str(exc))
            )
            return report

    # --- state root + .env ---
    default_sr = Path(
        os.environ.get("TWINBOX_STATE_ROOT", str(Path.home() / ".twinbox"))
    ).expanduser()
    try:
        sr = resolve_state_root(default_sr)
    except PathResolutionError as exc:
        if dry_run:
            sr = default_sr
        else:
            report.ok = False
            report.steps.append(
                DeployStepResult("resolve_state_root", "failed", str(exc))
            )
            return report

    report.state_root = str(sr)
    dotenv = load_env_file(sr / ".env") if sync_env_from_dotenv else {}

    missing_required: list[str] = []
    if sync_env_from_dotenv:
        for key in OPENCLAW_REQUIRED_MAIL_KEYS:
            if not (dotenv.get(key) or "").strip():
                missing_required.append(key)

    if strict and sync_env_from_dotenv and missing_required:
        report.ok = False
        report.steps.append(
            DeployStepResult(
                "merge_openclaw_json",
                "failed",
                "--strict: state root .env missing required keys for OpenClaw skill: "
                + ", ".join(missing_required),
                {"missing_required_env_in_dotenv": missing_required},
            )
        )
        return report

    # --- merge openclaw.json ---
    json_path = och / "openclaw.json"
    try:
        existing = load_openclaw_json(json_path)
    except ValueError as exc:
        report.ok = False
        report.steps.append(
            DeployStepResult("merge_openclaw_json", "failed", str(exc))
        )
        return report

    base = existing
    frag_resolved: Path | None = None
    frag_explicit = fragment_path is not None
    if no_fragment:
        report.steps.append(
            DeployStepResult(
                "merge_openclaw_fragment",
                "skipped",
                "--no-fragment",
            )
        )
    elif fragment_path is not None:
        frag_resolved = fragment_path.expanduser()
        if not frag_resolved.is_file():
            report.ok = False
            report.steps.append(
                DeployStepResult(
                    "merge_openclaw_fragment",
                    "failed",
                    f"Fragment file not found: {frag_resolved}",
                )
            )
            return report
    else:
        candidate = default_openclaw_fragment_path(cr)
        frag_resolved = candidate if candidate.is_file() else None

    if frag_resolved is not None:
        try:
            fragment_data = load_openclaw_json(frag_resolved)
        except ValueError as exc:
            report.ok = False
            report.steps.append(
                DeployStepResult("merge_openclaw_fragment", "failed", str(exc))
            )
            return report
        base = deep_merge_openclaw(existing, fragment_data)
        frag_msg = f"Deep-merged fragment from {frag_resolved}"
        if dry_run:
            report.steps.append(
                DeployStepResult(
                    "merge_openclaw_fragment",
                    "dry_run",
                    frag_msg,
                    {"path": str(frag_resolved), "explicit": frag_explicit},
                )
            )
        else:
            report.steps.append(
                DeployStepResult(
                    "merge_openclaw_fragment",
                    "ok",
                    frag_msg,
                    {"path": str(frag_resolved), "explicit": frag_explicit},
                )
            )
    elif not no_fragment:
        report.steps.append(
            DeployStepResult(
                "merge_openclaw_fragment",
                "skipped",
                f"No {default_openclaw_fragment_path(cr)} (optional)",
            )
        )

    merged = merge_twinbox_openclaw_entry(
        base,
        dotenv=dotenv,
        sync_env_from_dotenv=sync_env_from_dotenv,
    )

    if dry_run:
        report.steps.append(
            DeployStepResult(
                "merge_openclaw_json",
                "dry_run",
                f"Would write {json_path}",
                {
                    "sync_env_from_dotenv": sync_env_from_dotenv,
                    "missing_required_env_in_dotenv": missing_required,
                },
            )
        )
    else:
        try:
            atomic_write_json(json_path, merged)
            msg = "Merged skills.entries.twinbox"
            if sync_env_from_dotenv and missing_required:
                msg += (
                    f"; warning: state .env missing keys: {', '.join(missing_required)}"
                )
            report.steps.append(
                DeployStepResult(
                    "merge_openclaw_json",
                    "ok",
                    msg,
                    {
                        "missing_required_env_in_dotenv": missing_required,
                    },
                )
            )
        except OSError as exc:
            report.ok = False
            report.steps.append(
                DeployStepResult("merge_openclaw_json", "failed", str(exc))
            )
            return report

    # --- SKILL.md ---
    if not skill_src.is_file():
        report.ok = False
        report.steps.append(
            DeployStepResult(
                "sync_skill_md",
                "failed",
                f"Missing {skill_src}",
            )
        )
        return report

    if dry_run:
        report.steps.append(
            DeployStepResult(
                "sync_skill_md",
                "dry_run",
                f"Would copy {skill_src} -> {skill_dest}",
            )
        )
    else:
        try:
            skill_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_src, skill_dest)
            report.steps.append(
                DeployStepResult("sync_skill_md", "ok", f"Copied to {skill_dest}")
            )
        except OSError as exc:
            report.ok = False
            report.steps.append(
                DeployStepResult("sync_skill_md", "failed", str(exc))
            )
            return report

    # --- gateway restart ---
    if not restart_gateway:
        report.steps.append(
            DeployStepResult("gateway_restart", "skipped", "--no-restart")
        )
        return report

    if dry_run:
        report.steps.append(
            DeployStepResult(
                "gateway_restart",
                "dry_run",
                f"Would run: {openclaw_bin} gateway restart",
            )
        )
        return report

    try:
        proc = run(
            [openclaw_bin, "gateway", "restart"],
            cwd=str(cr),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            report.ok = False
            report.steps.append(
                DeployStepResult(
                    "gateway_restart",
                    "failed",
                    f"{openclaw_bin} gateway restart failed",
                    {
                        "returncode": proc.returncode,
                        "stderr": (proc.stderr or "")[-4000:],
                    },
                )
            )
        else:
            report.steps.append(
                DeployStepResult(
                    "gateway_restart",
                    "ok",
                    "Gateway restart issued",
                    {"stdout_tail": (proc.stdout or "")[-2000:]},
                )
            )
    except OSError as exc:
        report.ok = False
        report.steps.append(
            DeployStepResult("gateway_restart", "failed", str(exc))
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
) -> OpenClawDeployReport:
    """Undo host wiring done by :func:`run_openclaw_deploy` (narrow scope).

    Removes ``skills.entries.twinbox``, deletes ``~/.openclaw/skills/twinbox/``,
    optionally removes ``~/.config/twinbox/`` (code-root / state-root pointers).

    Does **not** remove ``~/.twinbox`` (mail state), OpenClaw plugins, cron,
    systemd bridge, or ``uninstall_openclaw_twinbox.sh`` scope — use that script
    for a full teardown.
    """
    run = run_subprocess or subprocess.run
    report = OpenClawDeployReport(ok=True, steps=[])

    try:
        cr = resolve_code_root(code_root or Path.cwd())
        report.code_root = str(cr)
    except PathResolutionError:
        report.code_root = ""

    default_sr = Path(
        os.environ.get("TWINBOX_STATE_ROOT", str(Path.home() / ".twinbox"))
    ).expanduser()
    try:
        sr = resolve_state_root(default_sr)
        report.state_root = str(sr)
    except PathResolutionError:
        report.state_root = str(default_sr)

    och = (openclaw_home or Path.home() / ".openclaw").expanduser()
    report.openclaw_home = str(och)
    report.openclaw_json = str(och / "openclaw.json")
    skill_dir = och / "skills" / "twinbox"
    report.skill_dest = str(skill_dir / "SKILL.md")

    json_path = och / "openclaw.json"
    try:
        existing = load_openclaw_json(json_path)
    except ValueError as exc:
        report.ok = False
        report.steps.append(
            DeployStepResult("strip_openclaw_json", "failed", str(exc))
        )
        return report

    stripped, had_entry = remove_twinbox_skill_entry_from_openclaw(existing)

    if dry_run:
        report.steps.append(
            DeployStepResult(
                "strip_openclaw_json",
                "dry_run",
                f"Would remove skills.entries.twinbox from {json_path}",
                {"had_twinbox_entry": had_entry},
            )
        )
    else:
        if had_entry:
            try:
                atomic_write_json(json_path, stripped)
                report.steps.append(
                    DeployStepResult(
                        "strip_openclaw_json",
                        "ok",
                        "Removed skills.entries.twinbox",
                    )
                )
            except OSError as exc:
                report.ok = False
                report.steps.append(
                    DeployStepResult("strip_openclaw_json", "failed", str(exc))
                )
                return report
        else:
            report.steps.append(
                DeployStepResult(
                    "strip_openclaw_json",
                    "skipped",
                    "No skills.entries.twinbox present",
                )
            )

    # --- skill directory ---
    if dry_run:
        report.steps.append(
            DeployStepResult(
                "remove_skill_dir",
                "dry_run",
                f"Would remove directory {skill_dir} if present",
                {"exists": skill_dir.is_dir()},
            )
        )
    else:
        if skill_dir.is_dir():
            try:
                shutil.rmtree(skill_dir)
                report.steps.append(
                    DeployStepResult(
                        "remove_skill_dir",
                        "ok",
                        f"Removed {skill_dir}",
                    )
                )
            except OSError as exc:
                report.ok = False
                report.steps.append(
                    DeployStepResult("remove_skill_dir", "failed", str(exc))
                )
                return report
        else:
            report.steps.append(
                DeployStepResult(
                    "remove_skill_dir",
                    "skipped",
                    "Skill directory not present",
                )
            )

    # --- ~/.config/twinbox ---
    cfg = config_dir()
    if dry_run:
        report.steps.append(
            DeployStepResult(
                "remove_twinbox_config",
                "dry_run",
                f"Would remove {cfg}" if remove_config else "Skipped (--remove-config not set)",
                {"remove_config": remove_config, "exists": cfg.is_dir()},
            )
        )
    elif remove_config:
        if cfg.is_dir():
            try:
                shutil.rmtree(cfg)
                report.steps.append(
                    DeployStepResult(
                        "remove_twinbox_config",
                        "ok",
                        f"Removed {cfg}",
                    )
                )
            except OSError as exc:
                report.ok = False
                report.steps.append(
                    DeployStepResult("remove_twinbox_config", "failed", str(exc))
                )
                return report
        else:
            report.steps.append(
                DeployStepResult(
                    "remove_twinbox_config",
                    "skipped",
                    "Config directory not present",
                )
            )
    else:
        report.steps.append(
            DeployStepResult(
                "remove_twinbox_config",
                "skipped",
                "Preserved ~/.config/twinbox (pass --remove-config to delete)",
            )
        )

    # --- gateway restart ---
    if not restart_gateway:
        report.steps.append(
            DeployStepResult("gateway_restart", "skipped", "--no-restart")
        )
        return report

    if dry_run:
        report.steps.append(
            DeployStepResult(
                "gateway_restart",
                "dry_run",
                f"Would run: {openclaw_bin} gateway restart",
            )
        )
        return report

    try:
        proc = run(
            [openclaw_bin, "gateway", "restart"],
            cwd=str(Path.home()),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            report.ok = False
            report.steps.append(
                DeployStepResult(
                    "gateway_restart",
                    "failed",
                    f"{openclaw_bin} gateway restart failed",
                    {
                        "returncode": proc.returncode,
                        "stderr": (proc.stderr or "")[-4000:],
                    },
                )
            )
        else:
            report.steps.append(
                DeployStepResult(
                    "gateway_restart",
                    "ok",
                    "Gateway restart issued",
                    {"stdout_tail": (proc.stdout or "")[-2000:]},
                )
            )
    except OSError as exc:
        report.ok = False
        report.steps.append(
            DeployStepResult("gateway_restart", "failed", str(exc))
        )

    return report
