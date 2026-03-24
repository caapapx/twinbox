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
    DigestView,
    ActionCard,
    ReviewItem,
    _get_phase4_dir,
    _is_stale,
    _load_yaml_artifact,
    _infer_action_type,
    _infer_risk_level,
    main,
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


class TestDigestView:
    """Test DigestView data model."""

    def test_to_dict_daily(self):
        """DigestView should serialize daily digest correctly."""
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
        view = DigestView(
            digest_type="daily",
            sections={
                "urgent": {"items": [card.to_dict()]},
                "pending": {"items": []},
            },
            generated_at="2026-03-23T10:00:00Z",
            stale=False,
        )
        result = view.to_dict()
        assert result["digest_type"] == "daily"
        assert "urgent" in result["sections"]
        assert result["stale"] is False

    def test_to_dict_weekly(self):
        """DigestView should serialize weekly digest correctly."""
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
        view = DigestView(
            digest_type="weekly",
            sections={
                "action_now": [card.to_dict()],
                "backlog": [],
                "important_changes": "Test changes",
            },
            generated_at="2026-03-23T10:00:00Z",
            stale=False,
        )
        result = view.to_dict()
        assert result["digest_type"] == "weekly"
        assert "action_now" in result["sections"]
        assert "important_changes" in result["sections"]
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


class TestActionCard:
    """Test ActionCard data model."""

    def test_to_dict(self):
        """ActionCard should serialize to dict correctly."""
        card = ActionCard(
            action_id="action-urgent-1",
            thread_id="thread-123",
            action_type="reply",
            why_now="Customer escalation requires response",
            risk_level="high",
            required_review_fields=["action_type", "why_now"],
            suggested_draft_mode="quick_reply",
        )
        result = card.to_dict()
        assert result["action_id"] == "action-urgent-1"
        assert result["thread_id"] == "thread-123"
        assert result["action_type"] == "reply"
        assert result["risk_level"] == "high"
        assert result["suggested_draft_mode"] == "quick_reply"
        assert result["required_review_fields"] == ["action_type", "why_now"]

    def test_to_dict_no_draft_mode(self):
        """ActionCard with None draft mode should serialize correctly."""
        card = ActionCard(
            action_id="action-1",
            thread_id="thread-456",
            action_type="archive",
            why_now="Thread closed",
            risk_level="low",
            required_review_fields=["action_type"],
            suggested_draft_mode=None,
        )
        result = card.to_dict()
        assert result["suggested_draft_mode"] is None

    def test_infer_action_type_reply(self):
        """Should infer reply from action_hint."""
        item = {"action_hint": "please reply to customer"}
        assert _infer_action_type(item) == "reply"

    def test_infer_action_type_forward(self):
        """Should infer forward from action_hint."""
        item = {"action_hint": "forward to team"}
        assert _infer_action_type(item) == "forward"

    def test_infer_action_type_archive(self):
        """Should infer archive from action_hint."""
        item = {"action_hint": "archive and close"}
        assert _infer_action_type(item) == "archive"

    def test_infer_action_type_default(self):
        """Should default to reply when hint is ambiguous."""
        item = {"action_hint": "do something"}
        assert _infer_action_type(item) == "reply"

    def test_infer_risk_level_high(self):
        """Urgency score >= 80 should be high risk."""
        item = {"urgency_score": 90}
        assert _infer_risk_level(item) == "high"

    def test_infer_risk_level_medium(self):
        """Urgency score 50-79 should be medium risk."""
        item = {"urgency_score": 65}
        assert _infer_risk_level(item) == "medium"

    def test_infer_risk_level_low(self):
        """Urgency score < 50 should be low risk."""
        item = {"urgency_score": 30}
        assert _infer_risk_level(item) == "low"


class TestReviewItem:
    """Test ReviewItem data model."""

    def test_to_dict(self):
        """ReviewItem should serialize to dict correctly."""
        item = ReviewItem(
            review_id="review-urgent-1",
            thread_id="thread-123",
            review_type="confidence_check",
            current_state="waiting_on_me",
            proposed_change="confirm_or_override",
            reason="Low confidence (0.50): needs action",
            created_at="2026-03-23T10:00:00Z",
        )
        result = item.to_dict()
        assert result["review_id"] == "review-urgent-1"
        assert result["thread_id"] == "thread-123"
        assert result["review_type"] == "confidence_check"
        assert result["current_state"] == "waiting_on_me"
        assert result["proposed_change"] == "confirm_or_override"


class TestActionCommands:
    """Test action CLI commands."""

    def test_action_suggest_empty_queue(self, monkeypatch, tmp_path):
        """action suggest with empty artifacts should return empty list."""
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
        phase4_dir = tmp_path / "runtime" / "validation" / "phase-4"
        phase4_dir.mkdir(parents=True)
        # No artifact files -> empty actions
        exit_code = main(["action", "suggest", "--json"])
        assert exit_code == 0

    def test_action_suggest_with_urgent_items(self, monkeypatch, tmp_path, capsys):
        """action suggest should project actions from urgent queue."""
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
        phase4_dir = tmp_path / "runtime" / "validation" / "phase-4"
        phase4_dir.mkdir(parents=True)

        import yaml
        urgent_data = {
            "generated_at": "2026-03-23T08:30:00",
            "daily_urgent": [
                {
                    "thread_key": "thread-A",
                    "why": "Customer escalation",
                    "urgency_score": 85,
                    "action_hint": "please reply",
                    "flow": "support",
                    "stage": "escalated",
                }
            ],
        }
        (phase4_dir / "daily-urgent.yaml").write_text(
            yaml.dump(urgent_data, allow_unicode=True), encoding="utf-8"
        )

        exit_code = main(["action", "suggest", "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        actions = json.loads(captured.out)
        assert len(actions) == 1
        assert actions[0]["thread_id"] == "thread-A"
        assert actions[0]["action_type"] == "reply"
        assert actions[0]["risk_level"] == "high"

    def test_action_materialize_not_found(self, monkeypatch, tmp_path):
        """action materialize with unknown id should return error."""
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
        phase4_dir = tmp_path / "runtime" / "validation" / "phase-4"
        phase4_dir.mkdir(parents=True)

        exit_code = main(["action", "materialize", "action-nonexistent"])
        assert exit_code == 1

    def test_action_materialize_success(self, monkeypatch, tmp_path, capsys):
        """action materialize with valid id should return action details."""
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
        phase4_dir = tmp_path / "runtime" / "validation" / "phase-4"
        phase4_dir.mkdir(parents=True)

        import yaml
        urgent_data = {
            "generated_at": "2026-03-23T08:30:00",
            "daily_urgent": [
                {
                    "thread_key": "thread-B",
                    "why": "Needs reply",
                    "urgency_score": 60,
                    "action_hint": "respond today",
                }
            ],
        }
        (phase4_dir / "daily-urgent.yaml").write_text(
            yaml.dump(urgent_data, allow_unicode=True), encoding="utf-8"
        )

        exit_code = main(["action", "materialize", "action-urgent-1", "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["action_id"] == "action-urgent-1"
        assert result["materialized"] is True
        assert "review_checklist" in result


class TestReviewCommands:
    """Test review CLI commands."""

    def test_review_list_empty(self, monkeypatch, tmp_path):
        """review list with empty artifacts should return empty list."""
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
        phase4_dir = tmp_path / "runtime" / "validation" / "phase-4"
        phase4_dir.mkdir(parents=True)
        exit_code = main(["review", "list", "--json"])
        assert exit_code == 0

    def test_review_list_low_confidence_items(self, monkeypatch, tmp_path, capsys):
        """review list should flag low-confidence threads."""
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
        phase4_dir = tmp_path / "runtime" / "validation" / "phase-4"
        phase4_dir.mkdir(parents=True)

        import yaml
        urgent_data = {
            "generated_at": "2026-03-23T08:30:00",
            "daily_urgent": [
                {
                    "thread_key": "thread-low",
                    # urgency_score=0 -> confidence=0 < 0.7 -> triggers review
                    "urgency_score": 0,
                    "stage": "open",
                    "why": "",
                }
            ],
        }
        (phase4_dir / "daily-urgent.yaml").write_text(
            yaml.dump(urgent_data, allow_unicode=True), encoding="utf-8"
        )

        exit_code = main(["review", "list", "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        reviews = json.loads(captured.out)
        assert len(reviews) >= 1
        assert any(r["thread_id"] == "thread-low" for r in reviews)

    def test_review_show_not_found(self, monkeypatch, tmp_path):
        """review show with unknown id should return error."""
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
        phase4_dir = tmp_path / "runtime" / "validation" / "phase-4"
        phase4_dir.mkdir(parents=True)
        exit_code = main(["review", "show", "review-nonexistent"])
        assert exit_code == 1

