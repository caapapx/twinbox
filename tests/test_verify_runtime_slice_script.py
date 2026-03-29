from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_runtime_slice.sh"


def test_verify_runtime_slice_script_lists_named_checks() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--list"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert lines == [
        "python-runtime",
        "python-loading",
        "python-openclaw-deploy",
        "go-entrypoint",
    ]


def test_verify_runtime_slice_script_dry_run_prints_commands() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "python3 -m pytest tests/test_daemon_rpc.py" in result.stdout
    assert "tests/test_loading_pipeline.py" in result.stdout
    assert "tests/test_openclaw_deploy_steps.py" in result.stdout
    assert "cd cmd/twinbox-go && go test ./..." in result.stdout
