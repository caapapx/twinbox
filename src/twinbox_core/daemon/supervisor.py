"""Optional daemon supervisor that restarts the Unix-socket daemon child."""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from twinbox_core.daemon.layout import ensure_daemon_dirs, supervisor_pid_path
from twinbox_core.paths import resolve_daemon_state_root

RESTART_DELAY_SEC = 0.5

_shutdown = False
_child: subprocess.Popen[bytes] | None = None


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _acquire_supervisor_lock(state_root: Path) -> int:
    ensure_daemon_dirs(state_root)
    path = supervisor_pid_path(state_root)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    os.fchmod(fd, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RuntimeError("daemon supervisor already running") from None
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 64).decode("utf-8", errors="ignore").strip()
    except OSError:
        raw = ""
    if raw.isdigit() and _is_pid_alive(int(raw)):
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        raise RuntimeError(f"daemon supervisor already running (pid {raw})")
    return fd


def _write_pid(fd: int, pid: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, f"{pid}\n".encode("utf-8"))
    os.fsync(fd)


def _cleanup(fd: int | None, state_root: Path) -> None:
    if fd is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        supervisor_pid_path(state_root).unlink(missing_ok=True)
    except OSError:
        pass


def _terminate_child() -> None:
    global _child
    child = _child
    if child is None:
        return
    if child.poll() is None:
        try:
            child.terminate()
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if child.poll() is not None:
                break
            time.sleep(0.05)
        if child.poll() is None:
            try:
                child.kill()
            except ProcessLookupError:
                pass
            child.wait(timeout=5.0)
    _child = None


def _install_signal_handlers() -> None:
    def _handle(_signum: int, _frame: object) -> None:
        global _shutdown
        _shutdown = True
        _terminate_child()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def run_supervisor_forever() -> int:
    global _child, _shutdown

    state_root = resolve_daemon_state_root()
    if not state_root.is_dir():
        print(f"state root does not exist: {state_root}", file=sys.stderr)
        return 2

    try:
        pid_fd = _acquire_supervisor_lock(state_root)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    _install_signal_handlers()
    _write_pid(pid_fd, os.getpid())

    try:
        while not _shutdown:
            env = os.environ.copy()
            env["TWINBOX_STATE_ROOT"] = str(state_root)
            _child = subprocess.Popen(
                [sys.executable, "-m", "twinbox_core.daemon"],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            exit_code = _child.wait()
            _child = None
            if _shutdown:
                break
            time.sleep(RESTART_DELAY_SEC)
            if exit_code == 0:
                # A clean child exit is still unexpected while supervised.
                continue
    finally:
        _terminate_child()
        _cleanup(pid_fd, state_root)

    return 0


if __name__ == "__main__":
    raise SystemExit(run_supervisor_forever())
