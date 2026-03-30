"""Vendor-safe OpenClaw bridge: user systemd units calling installed ``twinbox`` only."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from twinbox_core.openclaw_bridge import bridge_audit_path, bridge_state_path, load_bridge_state
from twinbox_core.orchestration import poll_bridge_events
from twinbox_core.paths import resolve_code_root, resolve_state_root

BRIDGE_SERVICE_NAME = "twinbox-openclaw-bridge.service"
BRIDGE_TIMER_NAME = "twinbox-openclaw-bridge.timer"
BRIDGE_ENV_BASENAME = "twinbox-openclaw-bridge.env"
BRIDGE_STATUS_BASENAME = "host-bridge-install.json"


def _xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser()


def bridge_env_path() -> Path:
    """Environment file for systemd ``host bridge poll`` (under ``~/.twinbox``)."""
    return Path.home() / ".twinbox" / BRIDGE_ENV_BASENAME


def legacy_bridge_env_path() -> Path:
    """Historical location (``~/.config/twinbox/``); removed alongside :func:`bridge_env_path` on uninstall."""
    return _xdg_config_home() / "twinbox" / BRIDGE_ENV_BASENAME


def bridge_unit_dir() -> Path:
    return _xdg_config_home() / "systemd" / "user"


def bridge_install_record_path(state_root: Path) -> Path:
    return state_root / "runtime" / "context" / BRIDGE_STATUS_BASENAME


def _which_twinbox_bin(explicit: str | None = None) -> str:
    if explicit and Path(explicit).is_file() and os.access(explicit, os.X_OK):
        return str(Path(explicit).resolve())
    env_bin = (os.environ.get("TWINBOX_BIN") or "").strip()
    if env_bin and Path(env_bin).is_file() and os.access(env_bin, os.X_OK):
        return str(Path(env_bin).resolve())
    which = shutil.which("twinbox")
    if which:
        return str(Path(which).resolve())
    code_root = (os.environ.get("TWINBOX_CODE_ROOT") or "").strip()
    if code_root:
        candidate = Path(code_root).expanduser() / "scripts" / "twinbox"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    raise RuntimeError(
        "Could not resolve twinbox executable. Pass --twinbox-bin, set TWINBOX_BIN, or use PATH / scripts/twinbox under TWINBOX_CODE_ROOT."
    )


def _render_service_unit(*, twinbox_bin: str) -> str:
    # Vendor-safe: only invokes installed twinbox; no repo scripts.
    return f"""[Unit]
Description=Twinbox OpenClaw cron bridge poller
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=%h/.twinbox/{BRIDGE_ENV_BASENAME}
WorkingDirectory=%h
ExecStart={twinbox_bin} host bridge poll --format json
"""


def _render_timer_unit() -> str:
    return """[Unit]
Description=Twinbox OpenClaw cron bridge poller timer

[Timer]
OnCalendar=*-*-* *:*:00
Persistent=true
Unit=twinbox-openclaw-bridge.service

[Install]
WantedBy=timers.target
"""


RunCmd = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _default_run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def _systemctl_user(args: list[str], *, run: RunCmd) -> subprocess.CompletedProcess[str]:
    return run(["systemctl", "--user", *args])


def _timer_enabled_active(*, run: RunCmd) -> tuple[bool, bool]:
    en = _systemctl_user(["is-enabled", BRIDGE_TIMER_NAME], run=run)
    active = _systemctl_user(["is-active", BRIDGE_TIMER_NAME], run=run)
    enabled = en.returncode == 0 and "enabled" in (en.stdout or "").strip().lower()
    is_active = active.returncode == 0 and (active.stdout or "").strip() == "active"
    return enabled, is_active


def install_host_bridge(
    *,
    state_root: Path,
    openclaw_bin: str = "openclaw",
    twinbox_bin: str | None = None,
    dry_run: bool = False,
    no_start: bool = False,
    run: RunCmd | None = None,
) -> dict[str, Any]:
    run = run or _default_run
    resolved_twinbox = _which_twinbox_bin(twinbox_bin)
    sr = state_root.expanduser().resolve()
    env_path = bridge_env_path()
    unit_dir = bridge_unit_dir()
    service_path = unit_dir / BRIDGE_SERVICE_NAME
    timer_path = unit_dir / BRIDGE_TIMER_NAME

    env_lines = [
        f"TWINBOX_STATE_ROOT={sr}",
        f"TWINBOX_CANONICAL_ROOT={sr}",
        f"OPENCLAW_BIN={openclaw_bin}",
        "",
    ]
    record = {
        "twinbox_bin": resolved_twinbox,
        "openclaw_bin": openclaw_bin,
        "state_root": str(sr),
        "env_file": str(env_path),
        "service_unit": str(service_path),
        "timer_unit": str(timer_path),
    }

    if dry_run:
        return {"status": "dry_run", **record}

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("".join(line + "\n" for line in env_lines), encoding="utf-8")

    unit_dir.mkdir(parents=True, exist_ok=True)
    service_path.write_text(_render_service_unit(twinbox_bin=resolved_twinbox), encoding="utf-8")
    timer_path.write_text(_render_timer_unit(), encoding="utf-8")

    dr = _systemctl_user(["daemon-reload"], run=run)
    if dr.returncode != 0:
        err = dr.stderr.strip() or dr.stdout.strip() or "daemon-reload failed"
        return {"status": "failed", "step": "daemon-reload", "error": err, **record}

    _systemctl_user(["enable", BRIDGE_TIMER_NAME], run=run)
    if not no_start:
        st = _systemctl_user(["start", BRIDGE_TIMER_NAME], run=run)
        if st.returncode != 0:
            err = st.stderr.strip() or st.stdout.strip() or "timer start failed"
            return {"status": "failed", "step": "timer_start", "error": err, **record}

    inst_path = bridge_install_record_path(sr)
    inst_path.parent.mkdir(parents=True, exist_ok=True)
    inst_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {"status": "ok", **record}


def remove_host_bridge(
    *,
    state_root: Path | None = None,
    dry_run: bool = False,
    run: RunCmd | None = None,
) -> dict[str, Any]:
    run = run or _default_run
    env_path = bridge_env_path()
    unit_dir = bridge_unit_dir()
    service_path = unit_dir / BRIDGE_SERVICE_NAME
    timer_path = unit_dir / BRIDGE_TIMER_NAME
    out: dict[str, Any] = {
        "removed_units": [str(service_path), str(timer_path)],
        "removed_env": str(env_path),
    }
    if dry_run:
        return {"status": "dry_run", **out}

    _systemctl_user(["stop", BRIDGE_TIMER_NAME], run=run)
    _systemctl_user(["disable", BRIDGE_TIMER_NAME], run=run)
    _systemctl_user(["daemon-reload"], run=run)
    for p in (service_path, timer_path):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        env_path.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        legacy_bridge_env_path().unlink(missing_ok=True)
    except OSError:
        pass
    if state_root is not None:
        try:
            bridge_install_record_path(state_root.expanduser().resolve()).unlink(missing_ok=True)
        except OSError:
            pass
    return {"status": "ok", **out}


def host_bridge_poll(
    *,
    code_root: Path,
    state_root: Path,
    dry_run: bool,
    limit: int,
    openclaw_bin: str,
) -> tuple[int, dict[str, object]]:
    return poll_bridge_events(
        code_root,
        state_root,
        dry_run=dry_run,
        limit=limit,
        openclaw_bin=openclaw_bin,
    )


def host_bridge_status(
    *,
    state_root: Path,
    openclaw_bin: str,
    twinbox_bin: str | None = None,
    run: RunCmd | None = None,
) -> dict[str, Any]:
    run = run or _default_run
    sr = state_root.expanduser().resolve()
    try:
        resolved_twinbox = _which_twinbox_bin(twinbox_bin)
    except RuntimeError as exc:
        resolved_twinbox = str(twinbox_bin or "")

    enabled, active = _timer_enabled_active(run=run)
    bridge_st = load_bridge_state(sr)
    last_polled = bridge_st.get("last_polled_at")
    last_status = bridge_st.get("last_status")
    unit_dir = bridge_unit_dir()
    audit = bridge_audit_path(sr)
    last_audit_line = None
    if audit.is_file():
        try:
            lines = audit.read_text(encoding="utf-8").strip().splitlines()
            if lines:
                last_audit_line = lines[-1]
        except OSError:
            pass

    install_record: dict[str, Any] = {}
    inst = bridge_install_record_path(sr)
    if inst.is_file():
        try:
            raw = json.loads(inst.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                install_record = raw
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "unit_file_service": str(unit_dir / BRIDGE_SERVICE_NAME),
        "unit_file_timer": str(unit_dir / BRIDGE_TIMER_NAME),
        "timer_enabled": enabled,
        "timer_active": active,
        "last_poll_status": last_status,
        "last_polled_at": last_polled,
        "openclaw_bin": openclaw_bin,
        "twinbox_bin": resolved_twinbox,
        "state_root": str(sr),
        "bridge_state_path": str(bridge_state_path(sr)),
        "last_audit_record": last_audit_line,
        "install_record": install_record,
    }


def bridge_health_check(
    *,
    code_root: Path,
    state_root: Path,
    openclaw_bin: str,
) -> dict[str, Any]:
    try:
        exit_code, payload = host_bridge_poll(
            code_root=code_root,
            state_root=state_root,
            dry_run=True,
            limit=5,
            openclaw_bin=openclaw_bin,
        )
        return {
            "ok": exit_code == 0,
            "exit_code": exit_code,
            "poll": payload,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def resolve_default_roots(code_root: Path | None) -> tuple[Path, Path]:
    cr = resolve_code_root(code_root or Path.cwd())
    default_sr = Path(os.environ.get("TWINBOX_STATE_ROOT", str(Path.home() / ".twinbox"))).expanduser()
    sr = resolve_state_root(default_sr)
    return cr, sr
