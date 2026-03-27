"""Unit tests for daemon handlers (no subprocess daemon)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from twinbox_core.daemon.handlers import (
    handle_cli_invoke,
    set_daemon_state_root,
    set_task_cli_runner,
)


@pytest.fixture(autouse=True)
def _reset_task_cli_runner() -> None:
    yield
    set_task_cli_runner(None)


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    root = tmp_path / "sr"
    (root / "runtime" / "context").mkdir(parents=True)
    return root


def test_handle_cli_invoke_timeout_maps_to_exit_124(tmp_state: Path) -> None:
    set_daemon_state_root(tmp_state)

    def boom(_argv: list[str], *, timeout: float, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=["x"], timeout=timeout)

    set_task_cli_runner(boom)
    out = handle_cli_invoke({"argv": ["--help"], "timeout_ms": 50})
    assert out["exit_code"] == 124
    assert "timeout" in out["stderr"].lower()
    assert out["cache"] == "bypass"


def test_handle_cli_invoke_unknown_cache_policy_treated_as_bypass(tmp_state: Path) -> None:
    set_daemon_state_root(tmp_state)
    seen: list[tuple[list[str], float]] = []

    def fake(argv: list[str], *, timeout: float, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        seen.append((list(argv), timeout))
        return subprocess.CompletedProcess(
            [sys.executable, "-m", "twinbox_core.task_cli", *argv],
            0,
            "ok",
            "",
        )

    set_task_cli_runner(fake)
    out = handle_cli_invoke({"argv": ["--help"], "cache_policy": "not-a-real-policy"})
    assert seen == [(["--help"], 300.0)]
    assert out["exit_code"] == 0
    assert out.get("cache") == "bypass"
