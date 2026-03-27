"""Unit tests for daemon handlers (no subprocess daemon)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from twinbox_core.daemon.handlers import handle_cli_invoke, set_daemon_state_root


@pytest.fixture
def tmp_state(tmp_path: Path) -> Path:
    root = tmp_path / "sr"
    (root / "runtime" / "context").mkdir(parents=True)
    return root


def test_handle_cli_invoke_timeout_maps_to_exit_124(tmp_state: Path) -> None:
    set_daemon_state_root(tmp_state)
    with patch("twinbox_core.daemon.handlers.subprocess.run") as run:
        run.side_effect = subprocess.TimeoutExpired(cmd=["x"], timeout=0.1)
        out = handle_cli_invoke({"argv": ["--help"], "timeout_ms": 50})
    assert out["exit_code"] == 124
    assert "timeout" in out["stderr"].lower()
    assert out["cache"] == "bypass"


def test_handle_cli_invoke_unknown_cache_policy_treated_as_bypass(tmp_state: Path) -> None:
    set_daemon_state_root(tmp_state)
    with patch("twinbox_core.daemon.handlers.subprocess.run") as run:
        cp = MagicMock()
        cp.returncode = 0
        cp.stdout = "ok"
        cp.stderr = ""
        run.return_value = cp
        out = handle_cli_invoke({"argv": ["--help"], "cache_policy": "not-a-real-policy"})
    run.assert_called_once()
    assert out["exit_code"] == 0
    assert out.get("cache") == "bypass"
