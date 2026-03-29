"""CLI-facing daemon lifecycle: start, stop, status, restart."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from twinbox_core.daemon import TWINBOX_PROTOCOL_VERSION
from twinbox_core.daemon.layout import pid_path, socket_path, supervisor_pid_path
from twinbox_core.paths import resolve_daemon_state_root


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


def _read_pid_file(state_root: Path) -> str:
    p = pid_path(state_root)
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except OSError:
        return ""


def _read_supervisor_pid_file(state_root: Path) -> str:
    p = supervisor_pid_path(state_root)
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except OSError:
        return ""


def _cleanup_stale_paths(state_root: Path) -> None:
    try:
        socket_path(state_root).unlink(missing_ok=True)
    except OSError:
        pass
    try:
        pid_path(state_root).unlink(missing_ok=True)
    except OSError:
        pass
    try:
        supervisor_pid_path(state_root).unlink(missing_ok=True)
    except OSError:
        pass


def rpc_call(
    state_root: Path,
    method: str,
    params: dict[str, Any],
    *,
    connect_timeout_sec: float = 3.0,
    io_timeout_sec: float = 30.0,
) -> dict[str, Any]:
    sp = socket_path(state_root)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(connect_timeout_sec)
    sock.connect(str(sp))
    req_id = 1
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": req_id,
        "twinbox_version": TWINBOX_PROTOCOL_VERSION,
    }
    sock.settimeout(io_timeout_sec)
    sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
    buf = bytearray()
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        nl = chunk.find(b"\n")
        if nl >= 0:
            buf.extend(chunk[:nl])
            break
        buf.extend(chunk)
    sock.close()
    return json.loads(bytes(buf).decode("utf-8"))


def daemon_reachable(state_root: Path) -> bool:
    try:
        resp = rpc_call(state_root, "ping", {}, connect_timeout_sec=2.0, io_timeout_sec=5.0)
    except OSError:
        return False
    except json.JSONDecodeError:
        return False
    return isinstance(resp, dict) and resp.get("result", {}).get("status") == "ok"


def _spawn_daemon_process(state_root: Path, argv: list[str]) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["TWINBOX_STATE_ROOT"] = str(state_root)
    return subprocess.Popen(
        argv,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def cmd_start(state_root: Path, *, supervise: bool = False) -> int:
    if daemon_reachable(state_root):
        print("daemon already running", file=sys.stderr)
        return 1
    raw = _read_pid_file(state_root)
    if raw.isdigit() and _is_pid_alive(int(raw)):
        print("daemon already running (pid file)", file=sys.stderr)
        return 1
    sup_raw = _read_supervisor_pid_file(state_root)
    if sup_raw.isdigit() and _is_pid_alive(int(sup_raw)):
        print("daemon supervisor already running", file=sys.stderr)
        return 1

    argv = (
        [sys.executable, "-m", "twinbox_core.daemon.supervisor"]
        if supervise
        else [sys.executable, "-m", "twinbox_core.daemon"]
    )
    proc = _spawn_daemon_process(state_root, argv)
    err: bytes | None = None
    for _ in range(100):
        time.sleep(0.1)
        if daemon_reachable(state_root):
            if proc.stderr:
                proc.stderr.close()
            message = "daemon started (supervised)" if supervise else "daemon started"
            print(message)
            return 0
        code = proc.poll()
        if code is not None:
            if proc.stderr:
                err = proc.stderr.read()
                proc.stderr.close()
            msg = err.decode("utf-8", errors="replace").strip() if err else ""
            print(f"daemon failed to start (exit {code})", file=sys.stderr)
            if msg:
                print(msg, file=sys.stderr)
            return 1
    if proc.stderr:
        proc.stderr.close()
    try:
        proc.terminate()
    except ProcessLookupError:
        pass
    print("daemon start timeout", file=sys.stderr)
    return 1


def cmd_stop(state_root: Path) -> int:
    sup_raw = _read_supervisor_pid_file(state_root)
    if sup_raw.isdigit():
        sup_pid = int(sup_raw)
        if not _is_pid_alive(sup_pid):
            try:
                supervisor_pid_path(state_root).unlink(missing_ok=True)
            except OSError:
                pass
        else:
            try:
                os.kill(sup_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(50):
                time.sleep(0.1)
                if not _is_pid_alive(sup_pid):
                    break
            if _is_pid_alive(sup_pid):
                try:
                    os.kill(sup_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                supervisor_pid_path(state_root).unlink(missing_ok=True)
            except OSError:
                pass

    raw = _read_pid_file(state_root)
    if not raw or not raw.isdigit():
        _cleanup_stale_paths(state_root)
        return 0
    pid = int(raw)
    if not _is_pid_alive(pid):
        _cleanup_stale_paths(state_root)
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _cleanup_stale_paths(state_root)
        return 0
    for _ in range(50):
        time.sleep(0.1)
        if not _is_pid_alive(pid):
            _cleanup_stale_paths(state_root)
            return 0
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    _cleanup_stale_paths(state_root)
    return 0


def cmd_restart(state_root: Path, *, supervise: bool | None = None) -> int:
    if supervise is None:
        sup_raw = _read_supervisor_pid_file(state_root)
        supervise = sup_raw.isdigit() and _is_pid_alive(int(sup_raw))
    cmd_stop(state_root)
    return cmd_start(state_root, supervise=supervise)


def cmd_status(state_root: Path, *, json_output: bool) -> int:
    raw = _read_pid_file(state_root)
    pid_alive = raw.isdigit() and _is_pid_alive(int(raw))
    sup_raw = _read_supervisor_pid_file(state_root)
    supervised = sup_raw.isdigit() and _is_pid_alive(int(sup_raw))
    ping_result: dict[str, Any] | None = None
    try:
        resp = rpc_call(state_root, "ping", {}, connect_timeout_sec=3.0, io_timeout_sec=5.0)
        if isinstance(resp, dict) and "result" in resp:
            ping_result = resp["result"]
    except OSError:
        pass
    except json.JSONDecodeError:
        pass

    if ping_result and ping_result.get("status") == "ok":
        cs = ping_result.get("cache_stats")
        if not isinstance(cs, dict):
            cs = {"hits": 0, "misses": 0, "size_mb": 0}
        body: dict[str, Any] = {
            "status": "running",
            "uptime_seconds": ping_result.get("uptime_seconds", 0),
            "cache_stats": {
                "hits": int(cs.get("hits", 0)),
                "misses": int(cs.get("misses", 0)),
                "size_mb": float(cs.get("size_mb", 0)),
            },
            "active_connections": ping_result.get("active_connections", 0),
            "pid": int(raw) if raw.isdigit() else None,
            "supervised": supervised,
            "supervisor_pid": int(sup_raw) if supervised else None,
            "twinbox_version": TWINBOX_PROTOCOL_VERSION,
        }
    else:
        body = {
            "status": "stopped",
            "uptime_seconds": None,
            "cache_stats": {"hits": 0, "misses": 0, "size_mb": 0},
            "active_connections": 0,
            "pid": int(raw) if raw.isdigit() and pid_alive else None,
            "supervised": supervised,
            "supervisor_pid": int(sup_raw) if supervised else None,
            "twinbox_version": TWINBOX_PROTOCOL_VERSION,
        }

    if json_output:
        print(json.dumps(body, ensure_ascii=False))
    else:
        print(body["status"])
        if body.get("pid") is not None:
            print(f"pid: {body['pid']}")
        if body.get("supervised"):
            print(f"supervisor_pid: {body['supervisor_pid']}")
        if body["status"] == "running":
            print(f"uptime_seconds: {body['uptime_seconds']}")
            print(f"active_connections: {body['active_connections']}")
    return 0


def main_daemon_subcommand(sub: str, *, json_output: bool = False, supervise: bool = False) -> int:
    state_root = resolve_daemon_state_root()
    if sub == "start":
        return cmd_start(state_root, supervise=supervise)
    if sub == "stop":
        return cmd_stop(state_root)
    if sub == "restart":
        return cmd_restart(state_root, supervise=supervise if supervise else None)
    if sub == "status":
        return cmd_status(state_root, json_output=json_output)
    print(f"unknown daemon subcommand: {sub}", file=sys.stderr)
    return 2
