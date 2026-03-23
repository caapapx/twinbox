"""Tests for task-facing CLI."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
import yaml

from twinbox_core.task_cli import (
    ThreadCard,
    QueueView,
    _get_phase4_dir,
    _is_stale,
    _load_yaml_artifact,
)


class TestPhase4DirResolution:
    """Test Phase 4 directory resolution logic."""

    def test_env_var_takes_precedence(self, monkeypatch, tmp_path):
        """TWINBOX_CANONICAL_ROOT env var should take precedence."""
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
        phase4_dir = _get_phase4_dir()
        assert phase4_dir == tmp_path / "runtime" / "validation" / "phase-4"

    def test_fallback_to_cwd(self, monkeypatch, tmp_path):
        """Should fall back to cwd when env var not set."""
        monkeypatch.delenv("TWINBOX_CANONICAL_ROOT", raising=False)
        monkeypatch.chdir(tmp_path)
        phase4_dir = _get_phase4_dir()
        assert phase4_dir == tmp_path / "runtime" / "validation" / "phase-4"


class TestThreadCard:
    """Test ThreadCard data model."""

    def test_to_dict(self):
        """ThreadCard should serialize to dict correctly."""
        card = ThreadCard(
            thread_id="thread-123",
            state="waiting_on_me",
            waiting_on="me",
            last_activity_at="2026-03-23T10:00:00Z",
            confidence=0.85,
            evidence_refs=["env-1", "env-2"],
            context_refs=["ctx-1"],
            why="Test reason",
        )
        result = card.to_dict()
        assert result["thread_id"] == "thread-123"
        assert result["state"] == "waiting_on_me"
        assert result["confidence"] == 0.85


class TestQueueView:
    """Test QueueView data model."""

    def test_to_dict(self):
        """QueueView should serialize to dict correctly."""
        card = ThreadCard(
            thread_id="thread-123",
            state="waiting_on_me",
            waiting_on="me",
            last_activity_at="2026-03-23T10:00:00Z",
            confidence=0.85,
            evidence_refs=["env-1"],
            context_refs=["ctx-1"],
            why="Test",
        )
        view = QueueView(
            queue_type="urgent",
            items=[card],
            rank_reason="Test ranking",
            review_required=False,
            generated_at="2026-03-23T10:00:00Z",
            stale=False,
        )
        result = view.to_dict()
        assert result["queue_type"] == "urgent"
        assert len(result["items"]) == 1
        assert result["stale"] is False


class TestHelperFunctions:
    """Test helper functions."""

    def test_load_yaml_artifact_missing_file(self, tmp_path):
        """Should return empty dict for missing file."""
        result = _load_yaml_artifact(tmp_path / "nonexistent.yaml")
        assert result == {}

    def test_load_yaml_artifact_valid_file(self, tmp_path):
        """Should load valid YAML file."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("key: value\n")
        result = _load_yaml_artifact(yaml_file)
        assert result == {"key": "value"}

    def test_is_stale_recent(self):
        """Recent timestamp should not be stale."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        assert not _is_stale(timestamp, max_age_hours=24)

    def test_is_stale_old(self):
        """Old timestamp should be stale."""
        old_timestamp = "2020-01-01T00:00:00Z"
        assert _is_stale(old_timestamp, max_age_hours=24)

