"""Unix socket JSON-RPC daemon server."""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import fcntl

from twinbox_core.daemon import TWINBOX_PROTOCOL_VERSION
from twinbox_core.daemon import metrics
from twinbox_core.daemon.handlers import handle_cli_invoke, handle_ping
from twinbox_core.daemon.layout import ensure_daemon_dirs, log_path, pid_path, socket_path
from twinbox_core.paths import resolve_state_root

logger = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 256 * 1024
SHUTDOWN_JOIN_SEC = 3.0

_shutdown = threading.Event()
_workers_lock = threading.Lock()
_workers: set[threading.Thread] = set()
_pid_fd: int | None = None


def _adjust_active(delta: int) -> None:
    metrics.adjust_active(delta)


def _register_worker(t: threading.Thread) -> None:
    with _workers_lock:
        _workers.add(t)


def _unregister_worker(t: threading.Thread) -> None:
    with _workers_lock:
        _workers.discard(t)


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


def _acquire_daemon_pid_lock(state_root: Path) -> int:
    """Exclusive non-blocking flock; caller must hold fd open until exit."""
    ensure_daemon_dirs(state_root)
    path = pid_path(state_root)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    os.fchmod(fd, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RuntimeError("daemon already running (pid file locked)") from None
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 64).decode("utf-8", errors="ignore").strip()
    except OSError:
        raw = ""
    if raw.isdigit():
        old = int(raw)
        if _is_pid_alive(old):
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            raise RuntimeError(f"daemon already running (pid {old})")
    return fd


def _write_pid(fd: int, pid: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, f"{pid}\n".encode("utf-8"))
    os.fsync(fd)


def _read_message_line(sock: socket.socket, max_bytes: int, idle_sec: float) -> bytes:
    buf = bytearray()
    sock.settimeout(idle_sec)
    while len(buf) < max_bytes:
        try:
            chunk = sock.recv(min(65536, max_bytes - len(buf)))
        except socket.timeout:
            raise TimeoutError("connection idle timeout") from None
        if not chunk:
            break
        nl = chunk.find(b"\n")
        if nl >= 0:
            buf.extend(chunk[:nl])
            return bytes(buf)
        buf.extend(chunk)
    return bytes(buf)


def _rpc_dispatch(method: str, params: dict[str, Any]) -> Any:
    if method == "ping":
        return handle_ping(params or {})
    if method == "cli_invoke":
        return handle_cli_invoke(params or {})
    raise ValueError(f"unknown method: {method}")


def _build_response(
    req_id: Any,
    result: Any | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": req_id,
        "twinbox_version": TWINBOX_PROTOCOL_VERSION,
    }
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    return msg


def _handle_connection(conn: socket.socket, idle_sec: float) -> None:
    _adjust_active(1)
    try:
        raw = _read_message_line(conn, MAX_REQUEST_BYTES, idle_sec)
        if not raw.strip():
            return
        try:
            req = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            err = _build_response(
                None,
                error={"code": -32700, "message": "Parse error", "data": str(exc)},
            )
            conn.sendall((json.dumps(err) + "\n").encode("utf-8"))
            return
        if not isinstance(req, dict):
            err = _build_response(None, error={"code": -32600, "message": "Invalid Request"})
            conn.sendall((json.dumps(err) + "\n").encode("utf-8"))
            return

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}
        if req.get("jsonrpc") != "2.0":
            resp = _build_response(req_id, error={"code": -32600, "message": "Invalid Request"})
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            return
        if not isinstance(method, str):
            resp = _build_response(req_id, error={"code": -32600, "message": "Invalid method"})
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            return
        if not isinstance(params, dict):
            resp = _build_response(req_id, error={"code": -32602, "message": "Invalid params"})
            conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
            return
        try:
            result = _rpc_dispatch(method, params)
        except Exception as exc:
            logger.exception("handler error")
            resp = _build_response(req_id, error={"code": -32603, "message": str(exc)})
        else:
            resp = _build_response(req_id, result=result)
        conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
    finally:
        _adjust_active(-1)


def _install_signal_handlers(listen_sock: socket.socket, state_root: Path, sock_path: Path) -> None:
    def _handle(signum: int, _frame: Any) -> None:
        logger.info("signal %s: shutting down", signum)
        _shutdown.set()
        try:
            listen_sock.close()
        except OSError:
            pass

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)


def _join_workers() -> None:
    deadline = time.monotonic() + SHUTDOWN_JOIN_SEC
    while time.monotonic() < deadline:
        with _workers_lock:
            alive = [t for t in _workers if t.is_alive()]
        if not alive:
            return
        for t in alive:
            t.join(timeout=max(0, deadline - time.monotonic()))
        time.sleep(0.05)


def _cleanup_runtime_files(state_root: Path, pid_fd: int | None, sock_path: Path) -> None:
    if pid_fd is not None:
        try:
            fcntl.flock(pid_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(pid_fd)
        except OSError:
            pass
    try:
        pid_path(state_root).unlink(missing_ok=True)
    except OSError:
        pass
    try:
        sock_path.unlink(missing_ok=True)
    except OSError:
        pass


def run_daemon_forever() -> int:
    global _pid_fd
    if os.name != "posix":
        print("twinbox daemon requires POSIX (Unix socket)", file=sys.stderr)
        return 2

    state_env = os.environ.get("TWINBOX_STATE_ROOT", "").strip()
    if state_env:
        state_root = Path(state_env).expanduser().resolve()
    else:
        state_root = resolve_state_root(Path.cwd())

    if not state_root.is_dir():
        print(f"state root does not exist: {state_root}", file=sys.stderr)
        return 2

    ensure_daemon_dirs(state_root)
    lf = log_path(state_root)
    lf.parent.mkdir(parents=True, exist_ok=True)
    lf.touch(exist_ok=True)
    os.chmod(lf, 0o600)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(lf, encoding="utf-8")],
        force=True,
    )

    sock_p = socket_path(state_root)
    run_p = sock_p.parent
    run_p.mkdir(parents=True, exist_ok=True)
    run_p.chmod(0o700)

    pid_fd: int | None = None
    listen: socket.socket | None = None
    try:
        try:
            pid_fd = _acquire_daemon_pid_lock(state_root)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

        _pid_fd = pid_fd

        if sock_p.exists():
            try:
                sock_p.unlink()
            except OSError as exc:
                logger.warning("could not remove stale socket: %s", exc)

        listen = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listen.bind(str(sock_p))
            os.chmod(sock_p, 0o600)
        except OSError as exc:
            logger.error("bind failed: %s", exc)
            _cleanup_runtime_files(state_root, pid_fd, sock_p)
            return 1

        _write_pid(pid_fd, os.getpid())
        listen.listen(128)
        idle_sec = float(os.environ.get("TWINBOX_DAEMON_CONN_IDLE_SEC", "30"))

        _install_signal_handlers(listen, state_root, sock_p)
        logger.info("daemon listening on %s", sock_p)

        while not _shutdown.is_set():
            try:
                conn, _addr = listen.accept()
            except OSError:
                break

            def run_client(c: socket.socket = conn) -> None:
                try:
                    _handle_connection(c, idle_sec)
                finally:
                    try:
                        c.close()
                    except OSError:
                        pass
                    _unregister_worker(threading.current_thread())

            t = threading.Thread(target=run_client, daemon=True)
            _register_worker(t)
            t.start()

    finally:
        _join_workers()
        if listen is not None:
            try:
                listen.close()
            except OSError:
                pass
        _cleanup_runtime_files(state_root, pid_fd, sock_p)
        logger.info("daemon exited")
    return 0

