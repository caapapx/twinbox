"""Daemon paths under state root."""

from __future__ import annotations

from pathlib import Path


def run_dir(state_root: Path) -> Path:
    return state_root / "run"


def logs_dir(state_root: Path) -> Path:
    return state_root / "logs"


def socket_path(state_root: Path) -> Path:
    return run_dir(state_root) / "daemon.sock"


def pid_path(state_root: Path) -> Path:
    return run_dir(state_root) / "daemon.pid"


def log_path(state_root: Path) -> Path:
    return logs_dir(state_root) / "daemon.log"


def ensure_daemon_dirs(state_root: Path) -> None:
    r = run_dir(state_root)
    lg = logs_dir(state_root)
    r.mkdir(parents=True, exist_ok=True)
    lg.mkdir(parents=True, exist_ok=True)
    r.chmod(0o700)
