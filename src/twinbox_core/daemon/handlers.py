"""JSON-RPC method handlers (daemon worker thread)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from twinbox_core.daemon import TWINBOX_PROTOCOL_VERSION
from twinbox_core.daemon import invoke_cache
from twinbox_core.daemon import metrics

_START_MONO = time.monotonic()
_DAEMON_STATE_ROOT: Path | None = None


def set_daemon_state_root(root: Path) -> None:
    global _DAEMON_STATE_ROOT
    _DAEMON_STATE_ROOT = root


def handle_imap_pool_stats(_params: dict[str, Any]) -> dict[str, Any]:
    from twinbox_core import imap_pool

    return imap_pool.pool_stats()


def handle_ping(_params: dict[str, Any]) -> dict[str, Any]:
    hits, misses = metrics.cache_counters()
    return {
        "status": "ok",
        "uptime_seconds": int(time.monotonic() - _START_MONO),
        "twinbox_version": TWINBOX_PROTOCOL_VERSION,
        "active_connections": metrics.active_connection_count(),
        "cache_stats": {
            "hits": hits,
            "misses": misses,
            "size_mb": invoke_cache.approx_size_mb(),
        },
    }


def handle_cli_invoke(params: dict[str, Any]) -> dict[str, Any]:
    root = _DAEMON_STATE_ROOT
    if root is None:
        raise RuntimeError("daemon state root not initialized")

    argv = params.get("argv")
    if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
        raise ValueError("params.argv must be a list of strings")

    timeout_sec = float(os.environ.get("TWINBOX_DAEMON_CLI_TIMEOUT_SEC", "300"))
    tms = params.get("timeout_ms")
    if isinstance(tms, int) and tms > 0:
        timeout_sec = max(tms / 1000.0, 0.001)
    elif isinstance(tms, float) and tms > 0:
        timeout_sec = max(tms / 1000.0, 0.001)

    raw_policy = params.get("cache_policy")
    if isinstance(raw_policy, str):
        policy = raw_policy.strip().lower()
    else:
        policy = ""
    if policy in ("", "none", "bypass"):
        policy = ""

    fp = invoke_cache.context_mtime_fingerprint(root)

    if policy == "cache_only":
        hit = invoke_cache.cache_get(argv, fp)
        if hit is None:
            metrics.record_cache_miss()
            return {
                "exit_code": 124,
                "stdout": "",
                "stderr": "cli_invoke cache_only: no cached entry for current context fingerprint",
                "cache": "miss",
            }
        metrics.record_cache_hit()
        out = dict(hit)
        out["cache"] = "hit"
        return out

    if policy == "prefer_cache":
        hit = invoke_cache.cache_get(argv, fp)
        if hit is not None:
            metrics.record_cache_hit()
            out = dict(hit)
            out["cache"] = "hit"
            return out
        metrics.record_cache_miss()
    elif policy == "force_refresh":
        metrics.record_cache_miss()

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "twinbox_core.task_cli", *argv],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        return {
            "exit_code": 124,
            "stdout": "",
            "stderr": f"cli_invoke subprocess exceeded timeout ({timeout_sec}s)",
            "cache": "bypass",
        }
    result: dict[str, Any] = {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    if policy in ("prefer_cache", "force_refresh"):
        invoke_cache.cache_put(argv, fp, result)
        result["cache"] = "miss"
    else:
        result["cache"] = "bypass"
    return result
