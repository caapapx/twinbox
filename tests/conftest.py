"""Shared pytest fixtures for the twinbox test suite.

Auto-discovered by pytest. Available to all test modules under tests/.

Fixture categories:
- Phase 4 environment: phase4_root, write_phase4
- Sample artifact items: sample_urgent_item, sample_pending_item, sample_sla_item
- Timestamps: recent_timestamp, stale_timestamp
"""

from __future__ import annotations

import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"


# ---------------------------------------------------------------------------
# Phase 4 environment
# ---------------------------------------------------------------------------


@pytest.fixture
def phase4_root(monkeypatch, tmp_path):
    """Set TWINBOX_CANONICAL_ROOT and create the phase-4 artifact directory.

    Returns the ``runtime/validation/phase-4/`` Path so tests can write
    artifacts directly without repeating setup boilerplate.
    """
    phase4_dir = tmp_path / "runtime" / "validation" / "phase-4"
    phase4_dir.mkdir(parents=True)
    # resolve_state_root checks TWINBOX_STATE_ROOT before TWINBOX_CANONICAL_ROOT
    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
    return phase4_dir


@pytest.fixture
def write_phase4(phase4_root):
    """Factory: write a Phase 4 YAML artifact into the phase-4 dir.

    Usage::

        def test_something(write_phase4):
            write_phase4("daily-urgent.yaml", {"generated_at": ..., "daily_urgent": [...]})
    """

    def _write(filename: str, data: dict) -> Path:
        path = phase4_root / filename
        path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
        return path

    return _write


# ---------------------------------------------------------------------------
# Sample Phase 4 artifact items
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_urgent_item():
    """A fully-specified Phase 4 daily-urgent item with all explainability fields."""
    return {
        "thread_key": "thread-A",
        "why": "Customer escalation requires response",
        "reason_code": "escalation",
        "urgency_score": 85,
        "action_hint": "please reply",
        "flow": "support",
        "stage": "escalated",
        "waiting_on": "me",
        "evidence_source": "envelope-5",
    }


@pytest.fixture
def sample_pending_item():
    """A fully-specified Phase 4 pending-replies item."""
    return {
        "thread_key": "thread-B",
        "why": "Awaiting response from customer",
        "waiting_on_me": True,
        "flow": "project",
        "evidence_source": "envelope-8",
    }


@pytest.fixture
def sample_sla_item():
    """A fully-specified Phase 4 sla-risks item."""
    return {
        "thread_key": "thread-C",
        "risk_description": "SLA breach expected in 2 hours",
        "risk_type": "deadline_miss",
        "flow": "contract",
    }


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


@pytest.fixture
def recent_timestamp():
    """ISO 8601 timestamp for now — should never be considered stale."""
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def stale_timestamp():
    """ISO 8601 timestamp from two years ago — always stale."""
    return "2024-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Global stubs
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _pytest_src_on_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    """Daemon and other subprocesses need the package on PYTHONPATH (same as scripts/twinbox)."""
    if _SRC_ROOT.is_dir():
        prev = os.environ.get("PYTHONPATH", "")
        merged = str(_SRC_ROOT) + (os.pathsep + prev if prev else "")
        monkeypatch.setenv("PYTHONPATH", merged)


@pytest.fixture(autouse=True)
def _stub_openclaw_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub `openclaw` and `twinbox` for subprocess calls in schedule/bridge/deploy tests."""
    bindir = Path(tempfile.mkdtemp(prefix="twinbox-test-bin-"))
    openclaw = bindir / "openclaw"
    openclaw.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"${1:-}\" == \"gateway\" && \"${2:-}\" == \"restart\" ]]; then exit 0; fi\n"
        "if [[ \" $* \" == *\" cron.list \"* ]] || [[ \" $* \" == *\"cron.list\"* ]]; then echo '{\"jobs\":[]}'; exit 0; fi\n"
        "if [[ \" $* \" == *\" cron.runs \"* ]] || [[ \" $* \" == *\"cron.runs\"* ]]; then echo '{\"entries\":[]}'; exit 0; fi\n"
        "if [[ \"${1:-}\" == \"gateway\" && \"${2:-}\" == \"call\" ]]; then echo '{}'; exit 0; fi\n"
        "if [[ \"${1:-}\" == \"cron\" && \"${2:-}\" == \"list\" ]]; then echo '{\"jobs\":[]}'; exit 0; fi\n"
        "if [[ \"${1:-}\" == \"cron\" && \"${2:-}\" == \"add\" ]]; then echo '{\"id\":\"stub-job\"}'; exit 0; fi\n"
        "if [[ \"${1:-}\" == \"cron\" ]]; then exit 0; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    openclaw.chmod(openclaw.stat().st_mode | stat.S_IEXEC)
    twinbox = bindir / "twinbox"
    twinbox.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"${1:-}\" == \"host\" && \"${2:-}\" == \"bridge\" && \"${3:-}\" == \"poll\" ]]; then echo '{}'; exit 0; fi\n"
        "if [[ \"${1:-}\" == \"host\" && \"${2:-}\" == \"bridge\" && \"${3:-}\" == \"install\" ]]; then echo '{\"status\":\"ok\"}'; exit 0; fi\n"
        "exec python3 -m twinbox_core.task_cli \"$@\"\n",
        encoding="utf-8",
    )
    twinbox.chmod(twinbox.stat().st_mode | stat.S_IEXEC)
    systemctl = bindir / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"${1:-}\" == \"--user\" && \"${2:-}\" == \"is-enabled\" ]]; then echo enabled; exit 0; fi\n"
        "if [[ \"${1:-}\" == \"--user\" && \"${2:-}\" == \"is-active\" ]]; then echo active; exit 0; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    systemctl.chmod(systemctl.stat().st_mode | stat.S_IEXEC)
    path = str(bindir) + os.pathsep + os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", path)
