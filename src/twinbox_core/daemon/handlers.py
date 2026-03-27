"""JSON-RPC method handlers (daemon worker thread)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any

from twinbox_core.daemon import TWINBOX_PROTOCOL_VERSION
from twinbox_core.daemon import metrics

_START_MONO = time.monotonic()


def handle_ping(_params: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "ok",
        "uptime_seconds": int(time.monotonic() - _START_MONO),
        "twinbox_version": TWINBOX_PROTOCOL_VERSION,
        "active_connections": metrics.active_connection_count(),
    }


def handle_cli_invoke(params: dict[str, Any]) -> dict[str, Any]:
    argv = params.get("argv")
    if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
        raise ValueError("params.argv must be a list of strings")
    timeout_sec = int(os.environ.get("TWINBOX_DAEMON_CLI_TIMEOUT_SEC", "300"))
    proc = subprocess.run(
        [sys.executable, "-m", "twinbox_core.task_cli", *argv],
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        env=os.environ.copy(),
    )
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
