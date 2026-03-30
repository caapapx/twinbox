"""Tests for twinbox_core.daemon JSON-RPC and lifecycle."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from twinbox_core.daemon import TWINBOX_PROTOCOL_VERSION
from twinbox_core.daemon.layout import pid_path, socket_path
from twinbox_core.daemon.lifecycle import cmd_stop, main_daemon_subcommand, rpc_call


def _env_with_state_root(tmp: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["TWINBOX_STATE_ROOT"] = str(tmp)
    src = Path(__file__).resolve().parents[1] / "src"
    env["PYTHONPATH"] = str(src) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _run_cli(args: list[str], tmp: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "twinbox_core.task_cli", *args],
        env=_env_with_state_root(tmp),
        cwd=str(tmp),
        capture_output=True,
        text=True,
        check=check,
    )


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    (tmp_path / "runtime").mkdir()
    return tmp_path


def test_daemon_start_stop(state_root: Path) -> None:
    r = _run_cli(["daemon", "start"], state_root, check=False)
    assert r.returncode == 0, r.stderr
    assert pid_path(state_root).is_file()
    r2 = _run_cli(["daemon", "stop"], state_root, check=False)
    assert r2.returncode == 0, r2.stderr
    assert not pid_path(state_root).exists()


def test_daemon_ping(state_root: Path) -> None:
    assert _run_cli(["daemon", "start"], state_root).returncode == 0
    try:
        resp = rpc_call(state_root, "ping", {}, connect_timeout_sec=5.0, io_timeout_sec=5.0)
        assert resp["jsonrpc"] == "2.0"
        assert resp["twinbox_version"] == TWINBOX_PROTOCOL_VERSION
        assert resp["result"]["status"] == "ok"
        assert "uptime_seconds" in resp["result"]
        cs = resp["result"].get("cache_stats")
        assert isinstance(cs, dict)
        assert "hits" in cs and "misses" in cs
    finally:
        _run_cli(["daemon", "stop"], state_root, check=False)


def test_cli_invoke_help(state_root: Path) -> None:
    assert _run_cli(["daemon", "start"], state_root).returncode == 0
    try:
        resp = rpc_call(state_root, "cli_invoke", {"argv": ["--help"]}, connect_timeout_sec=5.0, io_timeout_sec=60.0)
        assert resp["result"]["exit_code"] == 0
        assert "usage" in resp["result"]["stdout"].lower()
    finally:
        _run_cli(["daemon", "stop"], state_root, check=False)


def test_cli_invoke_json(state_root: Path) -> None:
    assert _run_cli(["daemon", "start"], state_root).returncode == 0
    try:
        resp = rpc_call(
            state_root,
            "cli_invoke",
            {"argv": ["task", "todo", "--json"]},
            connect_timeout_sec=5.0,
            io_timeout_sec=120.0,
        )
        assert resp["result"]["exit_code"] == 0
        out = json.loads(resp["result"]["stdout"])
        assert isinstance(out, dict)
    finally:
        _run_cli(["daemon", "stop"], state_root, check=False)


def test_stale_pid_cleanup(state_root: Path) -> None:
    (state_root / "run").mkdir(parents=True, exist_ok=True)
    pid_path(state_root).write_text("2147483646\n", encoding="utf-8")
    r = _run_cli(["daemon", "start"], state_root, check=False)
    assert r.returncode == 0, r.stderr
    try:
        raw = pid_path(state_root).read_text().strip()
        assert raw.isdigit()
        assert int(raw) != 2147483646
    finally:
        _run_cli(["daemon", "stop"], state_root, check=False)


def test_socket_file_cleanup(state_root: Path) -> None:
    assert _run_cli(["daemon", "start"], state_root).returncode == 0
    _run_cli(["daemon", "stop"], state_root, check=False)
    sp = socket_path(state_root)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text("stale", encoding="utf-8")
    r = _run_cli(["daemon", "start"], state_root, check=False)
    assert r.returncode == 0, r.stderr
    try:
        assert sp.exists()
        assert sp.is_socket()
    finally:
        _run_cli(["daemon", "stop"], state_root, check=False)


def test_daemon_restart(state_root: Path) -> None:
    assert _run_cli(["daemon", "start"], state_root).returncode == 0
    pid1 = int(pid_path(state_root).read_text().strip())
    r = _run_cli(["daemon", "restart"], state_root, check=False)
    assert r.returncode == 0, r.stderr
    try:
        pid2 = int(pid_path(state_root).read_text().strip())
        assert pid1 != pid2
    finally:
        _run_cli(["daemon", "stop"], state_root, check=False)


def test_connection_timeout(state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWINBOX_DAEMON_CONN_IDLE_SEC", "1")
    assert _run_cli(["daemon", "start"], state_root).returncode == 0
    try:
        sp = socket_path(state_root)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(sp))
        t0 = time.monotonic()
        sock.settimeout(5.0)
        chunk = sock.recv(16)
        assert chunk == b""
        assert time.monotonic() - t0 >= 0.9
        sock.close()
    finally:
        _run_cli(["daemon", "stop"], state_root, check=False)


def test_graceful_shutdown(state_root: Path) -> None:
    assert _run_cli(["daemon", "start"], state_root).returncode == 0
    pid = int(pid_path(state_root).read_text().strip())
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not pid_path(state_root).exists():
            break
        time.sleep(0.05)
    assert not pid_path(state_root).exists()


def test_duplicate_start(state_root: Path) -> None:
    assert _run_cli(["daemon", "start"], state_root).returncode == 0
    try:
        r = _run_cli(["daemon", "start"], state_root, check=False)
        assert r.returncode == 1
    finally:
        _run_cli(["daemon", "stop"], state_root, check=False)


def test_stop_not_running(state_root: Path) -> None:
    r = _run_cli(["daemon", "stop"], state_root, check=False)
    assert r.returncode == 0


def test_cli_invoke_cache_only_miss_without_warm_cache(state_root: Path) -> None:
    (state_root / "runtime" / "context").mkdir(parents=True)
    assert _run_cli(["daemon", "start"], state_root).returncode == 0
    try:
        resp = rpc_call(
            state_root,
            "cli_invoke",
            {"argv": ["--help"], "cache_policy": "cache_only"},
            connect_timeout_sec=5.0,
            io_timeout_sec=60.0,
        )
        assert resp["result"]["exit_code"] == 124
        assert "cache_only" in resp["result"]["stderr"].lower()
        assert resp["result"].get("cache") == "miss"
    finally:
        _run_cli(["daemon", "stop"], state_root, check=False)


def test_unknown_rpc_method_returns_error(state_root: Path) -> None:
    assert _run_cli(["daemon", "start"], state_root).returncode == 0
    try:
        resp = rpc_call(
            state_root,
            "no_such_method",
            {},
            connect_timeout_sec=5.0,
            io_timeout_sec=5.0,
        )
        assert "error" in resp
        assert resp["error"]["code"] == -32603
    finally:
        _run_cli(["daemon", "stop"], state_root, check=False)


def test_cli_invoke_prefer_cache_hit(state_root: Path) -> None:
    (state_root / "runtime" / "context").mkdir(parents=True)
    assert _run_cli(["daemon", "start"], state_root).returncode == 0
    try:
        params = {"argv": ["--help"], "cache_policy": "prefer_cache"}
        r1 = rpc_call(state_root, "cli_invoke", params, connect_timeout_sec=5.0, io_timeout_sec=120.0)
        r2 = rpc_call(state_root, "cli_invoke", params, connect_timeout_sec=5.0, io_timeout_sec=120.0)
        assert r1["result"].get("cache") == "miss"
        assert r2["result"].get("cache") == "hit"
        assert r1["result"]["exit_code"] == r2["result"]["exit_code"] == 0
    finally:
        _run_cli(["daemon", "stop"], state_root, check=False)


def test_imap_pool_stats_rpc(state_root: Path) -> None:
    assert _run_cli(["daemon", "start"], state_root).returncode == 0
    try:
        resp = rpc_call(state_root, "imap_pool_stats", {}, connect_timeout_sec=5.0, io_timeout_sec=5.0)
        assert resp["result"]["enabled"] is False
    finally:
        _run_cli(["daemon", "stop"], state_root, check=False)


def test_invalid_rpc(state_root: Path) -> None:
    assert _run_cli(["daemon", "start"], state_root).returncode == 0
    try:
        sp = socket_path(state_root)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(str(sp))
        sock.sendall(b"not-json-at-all\n")
        buf = b""
        while True:
            c = sock.recv(4096)
            if not c:
                break
            buf += c
            if b"\n" in buf:
                break
        sock.close()
        line = buf.split(b"\n", 1)[0]
        msg = json.loads(line.decode())
        assert "error" in msg
    finally:
        _run_cli(["daemon", "stop"], state_root, check=False)


def test_status_json_inproc(state_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(state_root)
    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))
    assert main_daemon_subcommand("start") == 0
    try:
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))
        assert main_daemon_subcommand("status", json_output=True) == 0
    finally:
        cmd_stop(state_root)
