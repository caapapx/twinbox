"""Shared pytest fixtures for the twinbox test suite.

Auto-discovered by pytest. Available to all test modules under tests/.

Fixture categories:
- Phase 4 environment: phase4_root, write_phase4
- Sample artifact items: sample_urgent_item, sample_pending_item, sample_sla_item
- Timestamps: recent_timestamp, stale_timestamp
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


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
