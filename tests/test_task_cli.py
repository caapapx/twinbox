"""Tests for task-facing CLI (twinbox_core.task_cli).

Coverage areas
--------------
- Data object serialization and JSON round-trip
  (ThreadCard, QueueView, DigestView, ActionCard, ReviewItem)
- Helper function correctness and boundary values
  (_is_stale, _load_yaml_artifact, _infer_action_type, _infer_risk_level)
- CLI command routing and exit codes
- JSON output contract: required fields present, valid structure

Fixtures
--------
Shared setup (phase4_root, write_phase4, sample_* items) lives in conftest.py
to avoid repetition across test classes.
"""

from __future__ import annotations

import json

import pytest
import yaml

from twinbox_core.onboarding import OnboardingState, load_state, save_state
from twinbox_core.task_cli import (
    ActionCard,
    DigestView,
    QueueView,
    ReviewItem,
    ThreadCard,
    _get_phase4_dir,
    _infer_action_type,
    _infer_risk_level,
    _is_stale,
    _load_yaml_artifact,
    main,
)


# ---------------------------------------------------------------------------
# Phase 4 directory resolution
# ---------------------------------------------------------------------------


class TestPhase4DirResolution:
    """TWINBOX_STATE_ROOT governs the phase-4 path, with legacy fallback."""

    def test_state_root_env_takes_precedence(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path / "legacy"))
        assert _get_phase4_dir() == tmp_path / "runtime" / "validation" / "phase-4"

    def test_legacy_env_still_works(self, monkeypatch, tmp_path):
        monkeypatch.delenv("TWINBOX_STATE_ROOT", raising=False)
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
        assert _get_phase4_dir() == tmp_path / "runtime" / "validation" / "phase-4"

    def test_fallback_to_cwd(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        monkeypatch.delenv("TWINBOX_STATE_ROOT", raising=False)
        monkeypatch.delenv("TWINBOX_CANONICAL_ROOT", raising=False)
        monkeypatch.chdir(tmp_path)
        assert _get_phase4_dir() == tmp_path / "runtime" / "validation" / "phase-4"


# ---------------------------------------------------------------------------
# Data object serialization — JSON round-trip is the correctness bar
# ---------------------------------------------------------------------------


class TestThreadCard:
    """ThreadCard must round-trip through JSON without data loss."""

    _FIELDS = dict(
        thread_id="thread-123",
        state="waiting_on_me",
        waiting_on="me",
        last_activity_at="2026-03-23T10:00:00Z",
        confidence=0.85,
        evidence_refs=["env-1", "env-2"],
        context_refs=["ctx-1"],
        why="Test reason",
    )

    def test_to_dict_fields(self):
        card = ThreadCard(**self._FIELDS)
        result = card.to_dict()
        assert result["thread_id"] == "thread-123"
        assert result["state"] == "waiting_on_me"
        assert result["confidence"] == 0.85

    def test_to_dict_is_json_serializable(self):
        """to_dict must survive json.dumps — no custom types allowed."""
        card = ThreadCard(**self._FIELDS)
        roundtrip = json.loads(json.dumps(card.to_dict()))
        assert roundtrip["thread_id"] == "thread-123"
        assert roundtrip["evidence_refs"] == ["env-1", "env-2"]

    def test_to_dict_null_last_activity_serializes_to_json_null(self):
        card = ThreadCard(**{**self._FIELDS, "last_activity_at": None})
        roundtrip = json.loads(json.dumps(card.to_dict()))
        assert roundtrip["last_activity_at"] is None


class TestQueueView:
    """QueueView round-trip, including nested ThreadCards."""

    def _card(self):
        return ThreadCard(
            thread_id="t1", state="waiting_on_me", waiting_on="me",
            last_activity_at=None, confidence=0.9,
            evidence_refs=[], context_refs=[], why="test",
        )

    def test_to_dict_fields(self):
        view = QueueView(
            queue_type="urgent", items=[self._card()],
            rank_reason="Test", review_required=False,
            generated_at="2026-03-23T10:00:00Z", stale=False,
        )
        result = view.to_dict()
        assert result["queue_type"] == "urgent"
        assert len(result["items"]) == 1
        assert result["stale"] is False

    def test_to_dict_nested_items_are_json_serializable(self):
        view = QueueView(
            queue_type="urgent", items=[self._card()],
            rank_reason="Test", review_required=False,
            generated_at="2026-03-23T10:00:00Z", stale=False,
        )
        roundtrip = json.loads(json.dumps(view.to_dict()))
        assert roundtrip["items"][0]["thread_id"] == "t1"

    def test_to_dict_empty_items(self):
        view = QueueView(
            queue_type="pending", items=[],
            rank_reason="Test", review_required=True,
            generated_at="2026-03-23T10:00:00Z", stale=True,
        )
        roundtrip = json.loads(json.dumps(view.to_dict()))
        assert roundtrip["items"] == []
        assert roundtrip["stale"] is True


class TestDigestView:
    """DigestView round-trip for daily and weekly cadences."""

    def test_daily_is_json_serializable(self):
        view = DigestView(
            digest_type="daily",
            sections={"urgent": {"items": []}, "pending": {"items": []}},
            generated_at="2026-03-23T10:00:00Z",
            stale=False,
        )
        roundtrip = json.loads(json.dumps(view.to_dict()))
        assert roundtrip["digest_type"] == "daily"
        assert "urgent" in roundtrip["sections"]

    def test_weekly_sections_structure(self):
        """Weekly must have action_now, backlog, important_changes."""
        view = DigestView(
            digest_type="weekly",
            sections={
                "action_now": [],
                "backlog": [],
                "important_changes": "Key changes this week",
            },
            generated_at="2026-03-23T10:00:00Z",
            stale=False,
        )
        roundtrip = json.loads(json.dumps(view.to_dict()))
        assert roundtrip["digest_type"] == "weekly"
        assert "action_now" in roundtrip["sections"]
        assert "important_changes" in roundtrip["sections"]


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """_is_stale and _load_yaml_artifact edge cases."""

    # --- _load_yaml_artifact ---

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert _load_yaml_artifact(tmp_path / "nope.yaml") == {}

    def test_load_valid_yaml(self, tmp_path):
        f = tmp_path / "ok.yaml"
        f.write_text("key: value\n")
        assert _load_yaml_artifact(f) == {"key": "value"}

    def test_load_malformed_yaml_returns_empty_dict(self, tmp_path):
        """Malformed YAML must not propagate an exception."""
        f = tmp_path / "bad.yaml"
        f.write_text(": : : not yaml\n")
        assert _load_yaml_artifact(f) == {}

    def test_load_yaml_list_returns_empty_dict(self, tmp_path):
        """YAML root that is a list (not a dict) should be normalised to {}."""
        f = tmp_path / "list.yaml"
        f.write_text("- item1\n- item2\n")
        assert _load_yaml_artifact(f) == {}

    # --- _is_stale ---

    def test_recent_timestamp_is_not_stale(self, recent_timestamp):
        assert not _is_stale(recent_timestamp, max_age_hours=24)

    def test_old_timestamp_is_stale(self):
        assert _is_stale("2020-01-01T00:00:00Z", max_age_hours=24)

    def test_malformed_timestamp_treated_as_stale(self):
        """An un-parseable timestamp cannot be proven fresh — treat conservatively."""
        assert _is_stale("not-a-timestamp")
        assert _is_stale("")

    def test_none_timestamp_treated_as_stale(self):
        assert _is_stale(None)


# ---------------------------------------------------------------------------
# ActionCard — serialization + inference helpers
# ---------------------------------------------------------------------------


class TestActionCard:
    """ActionCard serialization and action/risk inference boundary tests."""

    def test_to_dict_is_json_serializable(self):
        card = ActionCard(
            action_id="action-1",
            thread_id="thread-123",
            action_type="reply",
            why_now="Customer escalation",
            risk_level="high",
            required_review_fields=["action_type", "why_now"],
            suggested_draft_mode="quick_reply",
        )
        roundtrip = json.loads(json.dumps(card.to_dict()))
        assert roundtrip["action_id"] == "action-1"
        assert roundtrip["required_review_fields"] == ["action_type", "why_now"]

    def test_to_dict_none_draft_mode_serializes_to_null(self):
        card = ActionCard(
            action_id="a2", thread_id="t", action_type="archive",
            why_now="Thread closed", risk_level="low",
            required_review_fields=[], suggested_draft_mode=None,
        )
        roundtrip = json.loads(json.dumps(card.to_dict()))
        assert roundtrip["suggested_draft_mode"] is None

    # --- _infer_action_type ---

    def test_infer_reply(self):
        assert _infer_action_type({"action_hint": "please reply to customer"}) == "reply"

    def test_infer_forward(self):
        assert _infer_action_type({"action_hint": "forward to team"}) == "forward"

    def test_infer_archive(self):
        assert _infer_action_type({"action_hint": "archive and close"}) == "archive"

    def test_infer_ambiguous_hint_defaults_to_reply(self):
        assert _infer_action_type({"action_hint": "do something"}) == "reply"

    def test_infer_missing_hint_key_defaults_to_reply(self):
        """Missing action_hint should default gracefully, not raise."""
        assert _infer_action_type({}) == "reply"

    def test_infer_action_type_is_case_insensitive(self):
        assert _infer_action_type({"action_hint": "PLEASE REPLY NOW"}) == "reply"
        assert _infer_action_type({"action_hint": "FORWARD This"}) == "forward"

    # --- _infer_risk_level boundaries ---

    def test_risk_high_above_80(self):
        assert _infer_risk_level({"urgency_score": 90}) == "high"

    def test_risk_boundary_80_is_high(self):
        """80 is the inclusive lower bound for 'high'."""
        assert _infer_risk_level({"urgency_score": 80}) == "high"

    def test_risk_boundary_79_is_medium(self):
        """79 falls just below 'high', landing in 'medium'."""
        assert _infer_risk_level({"urgency_score": 79}) == "medium"

    def test_risk_medium_mid_range(self):
        assert _infer_risk_level({"urgency_score": 65}) == "medium"

    def test_risk_boundary_50_is_medium(self):
        """50 is the inclusive lower bound for 'medium'."""
        assert _infer_risk_level({"urgency_score": 50}) == "medium"

    def test_risk_boundary_49_is_low(self):
        """49 falls just below 'medium', landing in 'low'."""
        assert _infer_risk_level({"urgency_score": 49}) == "low"

    def test_risk_low_below_50(self):
        assert _infer_risk_level({"urgency_score": 30}) == "low"

    def test_risk_missing_score_defaults_to_low(self):
        """Missing urgency_score should default gracefully, not raise."""
        assert _infer_risk_level({}) == "low"


# ---------------------------------------------------------------------------
# ReviewItem
# ---------------------------------------------------------------------------


class TestReviewItem:
    """ReviewItem serialization."""

    def test_to_dict_is_json_serializable(self):
        item = ReviewItem(
            review_id="review-1",
            thread_id="thread-123",
            review_type="confidence_check",
            current_state="waiting_on_me",
            proposed_change="confirm_or_override",
            reason="Low confidence (0.50): needs action",
            created_at="2026-03-23T10:00:00Z",
        )
        roundtrip = json.loads(json.dumps(item.to_dict()))
        assert roundtrip["review_id"] == "review-1"
        assert roundtrip["review_type"] == "confidence_check"


# ---------------------------------------------------------------------------
# CLI — 'action' commands
# ---------------------------------------------------------------------------


class TestActionCommands:
    """Integration tests for the 'action' subcommands."""

    def test_action_suggest_empty_returns_empty_list(self, phase4_root, capsys):
        """With no artifacts on disk, action suggest should return [] not an error."""
        assert main(["action", "suggest", "--json"]) == 0
        actions = json.loads(capsys.readouterr().out)
        assert actions == []

    def test_action_suggest_projects_from_urgent(
        self, write_phase4, capsys, sample_urgent_item
    ):
        """Actions are projected from the urgent queue with correct type and risk."""
        write_phase4("daily-urgent.yaml", {
            "generated_at": "2026-03-23T08:30:00",
            "daily_urgent": [sample_urgent_item],
        })
        assert main(["action", "suggest", "--json"]) == 0
        actions = json.loads(capsys.readouterr().out)
        assert len(actions) == 1
        assert actions[0]["thread_id"] == "thread-A"
        assert actions[0]["action_type"] == "reply"   # action_hint contains "reply"
        assert actions[0]["risk_level"] == "high"      # urgency_score=85 >= 80

    def test_action_suggest_json_output_contract(
        self, write_phase4, capsys, sample_urgent_item
    ):
        """Every action card must contain all required contract fields."""
        write_phase4("daily-urgent.yaml", {
            "generated_at": "2026-03-23T08:30:00",
            "daily_urgent": [sample_urgent_item],
        })
        main(["action", "suggest", "--json"])
        actions = json.loads(capsys.readouterr().out)
        required = {"action_id", "thread_id", "action_type", "why_now",
                    "risk_level", "required_review_fields", "suggested_draft_mode"}
        for action in actions:
            missing = required - action.keys()
            assert not missing, f"Action card missing fields: {missing}"

    def test_action_materialize_not_found_exits_1(self, phase4_root):
        assert main(["action", "materialize", "action-nonexistent"]) == 1

    def test_action_materialize_returns_full_contract(self, write_phase4, capsys):
        """Materialized action must include action_id, materialized=True, review_checklist."""
        write_phase4("daily-urgent.yaml", {
            "generated_at": "2026-03-23T08:30:00",
            "daily_urgent": [{
                "thread_key": "thread-B",
                "why": "Needs reply",
                "urgency_score": 60,
                "action_hint": "respond today",
            }],
        })
        assert main(["action", "materialize", "action-urgent-1", "--json"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["action_id"] == "action-urgent-1"
        assert result["materialized"] is True
        assert isinstance(result.get("review_checklist"), list)


# ---------------------------------------------------------------------------
# CLI — 'review' commands
# ---------------------------------------------------------------------------


class TestReviewCommands:
    """Integration tests for the 'review' subcommands."""

    def test_review_list_empty_returns_empty_list(self, phase4_root, capsys):
        assert main(["review", "list", "--json"]) == 0
        assert json.loads(capsys.readouterr().out) == []

    def test_review_list_flags_low_urgency_score(self, write_phase4, capsys):
        """Items with urgency_score in [1,69] have confidence < 0.7 -> flagged for review."""
        write_phase4("daily-urgent.yaml", {
            "generated_at": "2026-03-23T08:30:00",
            "daily_urgent": [{
                "thread_key": "thread-low",
                "urgency_score": 30,  # confidence=0.30 < 0.7 -> triggers confidence_check
                "stage": "open",
                "why": "some reason",
                "reason_code": "low_priority",
            }],
        })
        assert main(["review", "list", "--json"]) == 0
        reviews = json.loads(capsys.readouterr().out)
        assert any(r["thread_id"] == "thread-low" for r in reviews)

    def test_review_list_flags_missing_explainability(self, write_phase4, capsys):
        """High-confidence items without why/reason_code are flagged for explainability review."""
        write_phase4("daily-urgent.yaml", {
            "generated_at": "2026-03-23T08:30:00",
            "daily_urgent": [{
                "thread_key": "thread-no-explain",
                "urgency_score": 85,   # confidence=0.85 >= 0.7, no confidence_check
                # No "why" and no "reason_code" -> triggers explainability review
            }],
        })
        assert main(["review", "list", "--json"]) == 0
        reviews = json.loads(capsys.readouterr().out)
        assert any(r["thread_id"] == "thread-no-explain" for r in reviews)

    def test_review_list_json_contract(self, write_phase4, capsys):
        """Every review item must contain all required contract fields."""
        write_phase4("daily-urgent.yaml", {
            "generated_at": "2026-03-23T08:30:00",
            "daily_urgent": [{"thread_key": "t1", "urgency_score": 30, "why": ""}],
        })
        main(["review", "list", "--json"])
        reviews = json.loads(capsys.readouterr().out)
        required = {"review_id", "thread_id", "review_type", "current_state",
                    "proposed_change", "reason", "created_at"}
        for review in reviews:
            missing = required - review.keys()
            assert not missing, f"Review item missing fields: {missing}"

    def test_review_show_not_found_exits_1(self, phase4_root):
        assert main(["review", "show", "review-nonexistent"]) == 1


# ---------------------------------------------------------------------------
# CLI — queue / digest / thread smoke tests
# ---------------------------------------------------------------------------


class TestQueueDigestThreadCli:
    """End-to-end argv routing and output contract for queue/digest/thread."""

    def test_queue_list_json_returns_three_queue_types(self, phase4_root, capsys):
        """queue list --json must always return exactly urgent, pending, sla_risk."""
        assert main(["queue", "list", "--json"]) == 0
        queues = json.loads(capsys.readouterr().out)
        assert {q["queue_type"] for q in queues} == {"urgent", "pending", "sla_risk"}

    def test_queue_show_unknown_type_exits_1(self, phase4_root):
        assert main(["queue", "show", "not_a_queue", "--json"]) == 1

    def test_queue_explain_references_artifact_paths(self, phase4_root, capsys):
        assert main(["queue", "explain"]) == 0
        out = capsys.readouterr().out
        assert "daily-urgent.yaml" in out
        assert "phase-4" in out

    def test_queue_dismiss_writes_user_queue_state(self, phase4_root, capsys):
        (phase4_root / "activity-pulse.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-24T10:00:00+08:00",
                    "notifiable_items": [],
                    "recent_activity": [],
                    "needs_attention": [],
                    "thread_index": [
                        {
                            "thread_key": "项目北辰资源申请",
                            "latest_subject": "项目北辰资源申请",
                            "last_activity_at": "2026-03-24T09:30:00+08:00",
                            "latest_message_ref": "INBOX#501",
                            "new_message_count": 1,
                            "message_count": 1,
                            "unread_count": 1,
                            "queue_tags": ["pending"],
                            "waiting_on": "me",
                            "flow": "delivery",
                            "stage": "open",
                            "why": "等待资源确认",
                            "fingerprint": "INBOX#501|pending|me|delivery|open",
                            "query_terms": ["项目北辰"],
                            "score": 50,
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        assert main(["queue", "dismiss", "项目北辰资源申请", "--reason", "已处理", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["thread_key"] == "项目北辰资源申请"
        assert payload["status"] == "dismissed"

    def test_queue_complete_and_restore_return_json_contract(self, phase4_root, capsys):
        (phase4_root / "activity-pulse.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-24T10:00:00+08:00",
                    "notifiable_items": [],
                    "recent_activity": [],
                    "needs_attention": [],
                    "thread_index": [
                        {
                            "thread_key": "Invoice #2026-003",
                            "latest_subject": "Invoice #2026-003",
                            "last_activity_at": "2026-03-24T09:30:00+08:00",
                            "latest_message_ref": "INBOX#900",
                            "new_message_count": 1,
                            "message_count": 1,
                            "unread_count": 0,
                            "queue_tags": ["urgent"],
                            "waiting_on": "them",
                            "flow": "billing",
                            "stage": "approval",
                            "why": "等待对方确认",
                            "fingerprint": "INBOX#900|urgent|them|billing|approval",
                            "query_terms": ["invoice"],
                            "score": 60,
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        assert main(["queue", "complete", "Invoice #2026-003", "--action-taken", "已归档", "--json"]) == 0
        completed = json.loads(capsys.readouterr().out)
        assert completed["status"] == "completed"

        assert main(["queue", "restore", "Invoice #2026-003", "--json"]) == 0
        restored = json.loads(capsys.readouterr().out)
        assert restored["status"] == "restored"

    def test_schedule_list_json_exposes_defaults_and_overrides(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
        override_path = tmp_path / "runtime" / "context" / "schedule-overrides.yaml"
        override_path.parent.mkdir(parents=True, exist_ok=True)
        override_path.write_text(
            yaml.safe_dump(
                {
                    "timezone": "Asia/Shanghai",
                    "overrides": {
                        "daily-refresh": "30 9 * * *",
                    },
                },
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        assert main(["schedule", "list", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        by_name = {row["name"]: row for row in payload["schedules"]}

        assert payload["timezone"] == "Asia/Shanghai"
        assert by_name["daily-refresh"]["effective_cron"] == "30 9 * * *"
        assert by_name["daily-refresh"]["source"] == "override"
        assert by_name["weekly-refresh"]["source"] == "default"

    def test_schedule_update_and_reset_json_contract(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
        sync_results = iter(
            [
                {
                    "status": "updated",
                    "job_id": "job-1",
                    "job_name": "daily-refresh",
                    "scheduled_job": "daytime-sync",
                    "platform_name": "twinbox-daily-refresh",
                    "cron": "45 9 * * *",
                    "timezone": "Asia/Shanghai",
                    "message": "OpenClaw cron job synced.",
                },
                {
                    "status": "updated",
                    "job_id": "job-1",
                    "job_name": "daily-refresh",
                    "scheduled_job": "daytime-sync",
                    "platform_name": "twinbox-daily-refresh",
                    "cron": "30 8 * * *",
                    "timezone": "Asia/Shanghai",
                    "message": "OpenClaw cron job synced.",
                },
            ]
        )
        monkeypatch.setattr(
            "twinbox_core.schedule_override.sync_schedule_to_openclaw",
            lambda **_kwargs: next(sync_results),
        )

        assert main(["schedule", "update", "daily-refresh", "--cron", "45 9 * * *", "--json"]) == 0
        updated = json.loads(capsys.readouterr().out)
        assert updated["job_name"] == "daily-refresh"
        assert updated["effective_cron"] == "45 9 * * *"
        assert updated["platform_sync"]["status"] == "updated"
        assert updated["platform_sync"]["job_id"] == "job-1"
        assert updated["next_action"] == "OpenClaw cron job synced."

        assert main(["schedule", "reset", "daily-refresh", "--json"]) == 0
        reset = json.loads(capsys.readouterr().out)
        assert reset["job_name"] == "daily-refresh"
        assert reset["source"] == "default"
        assert reset["platform_sync"]["status"] == "updated"

    def test_schedule_update_invalid_cron_exits_1(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))

        assert main(["schedule", "update", "daily-refresh", "--cron", "30 9 * *", "--json"]) == 1

    def test_context_upsert_fact_writes_human_context_yaml(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))

        assert main(
            [
                "context",
                "upsert-fact",
                "--id",
                "customer-tier",
                "--type",
                "account",
                "--content",
                "A 级客户需优先回复",
            ]
        ) == 0
        out = capsys.readouterr().out
        human_context_path = tmp_path / "runtime" / "context" / "human-context.yaml"
        payload = yaml.safe_load(human_context_path.read_text(encoding="utf-8"))

        assert "已添加事实: customer-tier" in out
        assert str(human_context_path) in out
        assert payload["facts"][0]["id"] == "customer-tier"
        assert payload["facts"][0]["content"] == "A 级客户需优先回复"

    def test_onboarding_next_profile_setup_persists_profile_and_calibration_notes(
        self, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        save_state(
            tmp_path,
            OnboardingState(
                current_stage="profile_setup",
                completed_stages=["mailbox_login", "llm_setup"],
            ),
        )

        assert main(
            [
                "onboarding",
                "next",
                "--json",
                "--profile-notes",
                "  engineer; checks mail at 9:30  ",
                "--calibration-notes",
                "  本周重点关注部署审批，忽略 HR 通知。  ",
            ]
        ) == 0
        payload = json.loads(capsys.readouterr().out)
        state = load_state(tmp_path)
        human_context_path = tmp_path / "runtime" / "context" / "human-context.yaml"
        human_context = yaml.safe_load(human_context_path.read_text(encoding="utf-8"))

        assert payload["completed_stage"] == "profile_setup"
        assert payload["current_stage"] == "material_import"
        assert "notes" not in state.profile_data
        assert "calibration" not in state.profile_data
        assert human_context["profile_notes"] == "engineer; checks mail at 9:30"
        assert human_context["calibration"] == "本周重点关注部署审批，忽略 HR 通知。"

    def test_onboarding_next_ignores_calibration_notes_outside_profile_setup(
        self, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        save_state(
            tmp_path,
            OnboardingState(
                current_stage="material_import",
                completed_stages=["mailbox_login", "llm_setup", "profile_setup"],
                profile_data={"notes": "existing", "calibration": "keep me"},
            ),
        )

        assert main(
            [
                "onboarding",
                "next",
                "--json",
                "--calibration-notes",
                "should be ignored",
            ]
        ) == 0
        _ = json.loads(capsys.readouterr().out)
        state = load_state(tmp_path)

        assert state.profile_data["notes"] == "existing"
        assert state.profile_data["calibration"] == "keep me"

    def test_mailbox_setup_json_writes_env_and_runs_preflight(
        self, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_SETUP_IMAP_PASS", "secret-pass")
        monkeypatch.setattr(
            "twinbox_core.mailbox_detect.detect_to_env",
            lambda email, verbose=False: {
                "IMAP_HOST": "imap.example.com",
                "IMAP_PORT": "993",
                "IMAP_ENCRYPTION": "tls",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": "465",
                "SMTP_ENCRYPTION": "tls",
            },
        )
        monkeypatch.setattr(
            "twinbox_core.mailbox.run_preflight",
            lambda state_root=None: (0, {"status": "ok"}),
        )

        assert main(["mailbox", "setup", "--email", "user@example.com", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["status"] == "ok"
        assert payload["mailbox_config"]["IMAP_HOST"] == "imap.example.com"
        assert payload["config_file_path"] == str(tmp_path / "twinbox.json")
        config_payload = json.loads((tmp_path / "twinbox.json").read_text(encoding="utf-8"))
        assert config_payload["mailbox"]["imap"]["host"] == "imap.example.com"
        assert config_payload["mailbox"]["imap"]["password"] == "secret-pass"
        assert not (tmp_path / ".env").exists()

    def test_mailbox_setup_prompts_for_password_when_env_missing(
        self, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.delenv("TWINBOX_SETUP_IMAP_PASS", raising=False)
        monkeypatch.setattr("twinbox_core.task_cli._can_prompt_for_secret", lambda: True, raising=False)
        monkeypatch.setattr(
            "twinbox_core.task_cli._prompt_for_secret_value",
            lambda _prompt: "secret-pass",
            raising=False,
        )
        monkeypatch.setattr(
            "twinbox_core.mailbox_detect.detect_to_env",
            lambda email, verbose=False: {
                "IMAP_HOST": "imap.example.com",
                "IMAP_PORT": "993",
                "IMAP_ENCRYPTION": "tls",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": "465",
                "SMTP_ENCRYPTION": "tls",
            },
        )
        monkeypatch.setattr(
            "twinbox_core.mailbox.run_preflight",
            lambda state_root=None: (0, {"status": "ok"}),
        )

        assert main(["mailbox", "setup", "--email", "user@example.com", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["status"] == "ok"
        config_payload = json.loads((tmp_path / "twinbox.json").read_text(encoding="utf-8"))
        assert config_payload["mailbox"]["imap"]["password"] == "secret-pass"

    def test_mailbox_setup_reports_detection_and_validation_progress_in_terminal(
        self, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_SETUP_IMAP_PASS", "secret-pass")
        events: list[tuple[str, str]] = []

        class _Progress:
            def __init__(self, title: str) -> None:
                events.append(("progress", title))

            def update(self, message: str) -> None:
                events.append(("update", message))

            def finish(self, message: str) -> None:
                events.append(("finish", message))

            def fail(self, message: str) -> None:
                events.append(("fail", message))

        monkeypatch.setattr(
            "twinbox_core.task_cli._create_cli_progress",
            lambda title, enabled=True: _Progress(title),
            raising=False,
        )
        monkeypatch.setattr(
            "twinbox_core.mailbox_detect.detect_to_env",
            lambda email, verbose=False: {
                "IMAP_HOST": "imap.example.com",
                "IMAP_PORT": "993",
                "IMAP_ENCRYPTION": "tls",
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": "465",
                "SMTP_ENCRYPTION": "tls",
            },
        )
        monkeypatch.setattr(
            "twinbox_core.mailbox.run_preflight",
            lambda state_root=None: (0, {"status": "ok"}),
        )

        assert main(["mailbox", "setup", "--email", "user@example.com"]) == 0
        _ = capsys.readouterr()

        assert ("progress", "Detecting mailbox settings") in events
        assert ("progress", "Checking mailbox settings") in events

    def test_config_set_llm_json_writes_twinbox_json(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_SETUP_API_KEY", "sk-test")

        assert main(
            [
                "config",
                "set-llm",
                "--provider",
                "openai",
                "--api-url",
                "https://example.com/v1/chat/completions",
                "--model",
                "gpt-test",
                "--json",
            ]
        ) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["status"] == "ok"
        assert payload["config_file_path"] == str(tmp_path / "twinbox.json")
        config_payload = json.loads((tmp_path / "twinbox.json").read_text(encoding="utf-8"))
        assert config_payload["llm"]["provider"] == "openai"
        assert config_payload["llm"]["api_url"] == "https://example.com/v1/chat/completions"
        assert config_payload["llm"]["model"] == "gpt-test"
        assert config_payload["llm"]["api_key"] == "sk-test"
        assert not (tmp_path / ".env").exists()

    def test_config_set_llm_prompts_for_api_key_when_env_missing(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.delenv("TWINBOX_SETUP_API_KEY", raising=False)
        monkeypatch.setattr("twinbox_core.task_cli._can_prompt_for_secret", lambda: True, raising=False)
        monkeypatch.setattr(
            "twinbox_core.task_cli._prompt_for_secret_value",
            lambda _prompt: "sk-test",
            raising=False,
        )

        assert main(
            [
                "config",
                "set-llm",
                "--provider",
                "openai",
                "--api-url",
                "https://example.com/v1/chat/completions",
                "--model",
                "gpt-test",
                "--json",
            ]
        ) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["status"] == "ok"
        config_payload = json.loads((tmp_path / "twinbox.json").read_text(encoding="utf-8"))
        assert config_payload["llm"]["api_key"] == "sk-test"

    def test_config_set_llm_reports_validation_progress_in_terminal(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_SETUP_API_KEY", "sk-test")
        events: list[tuple[str, str]] = []

        class _Progress:
            def __init__(self, title: str) -> None:
                events.append(("progress", title))

            def update(self, message: str) -> None:
                events.append(("update", message))

            def finish(self, message: str) -> None:
                events.append(("finish", message))

            def fail(self, message: str) -> None:
                events.append(("fail", message))

        monkeypatch.setattr(
            "twinbox_core.task_cli._create_cli_progress",
            lambda title, enabled=True: _Progress(title),
            raising=False,
        )

        assert main(
            [
                "config",
                "set-llm",
                "--provider",
                "openai",
                "--api-url",
                "https://example.com/v1/chat/completions",
                "--model",
                "gpt-test",
            ]
        ) == 0
        _ = capsys.readouterr()

        assert ("progress", "Validating LLM configuration") in events

    def test_config_show_json_reads_single_twinbox_config(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        (tmp_path / "twinbox.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "mailbox": {
                        "email": "user@example.com",
                        "imap": {"host": "imap.example.com", "port": "993", "login": "user@example.com"},
                        "smtp": {"host": "smtp.example.com", "port": "465", "login": "user@example.com"},
                    },
                    "llm": {
                        "provider": "openai",
                        "model": "gpt-test",
                        "api_url": "https://example.com/v1/chat/completions",
                        "api_key": "sk-test",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        assert main(["config", "show", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["config_file_path"] == str(tmp_path / "twinbox.json")
        assert payload["mailbox"]["email"] == "user@example.com"
        assert payload["llm"]["provider"] == "openai"
        assert payload["llm"]["api_key_masked"].startswith("***")

    def test_digest_daily_json_schema(self, phase4_root, capsys):
        """Daily digest JSON must include digest_type, sections, generated_at, stale."""
        assert main(["digest", "daily", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        for field in ("digest_type", "sections", "generated_at", "stale"):
            assert field in payload, f"Missing field: {field}"
        assert payload["digest_type"] == "daily"
        assert isinstance(payload["sections"], dict)

    def test_digest_daily_human_output_uses_markdown_sections(
        self, write_phase4, capsys, sample_urgent_item, sample_pending_item, sample_sla_item
    ):
        write_phase4("daily-urgent.yaml", {"generated_at": "2026-03-23T08:30:00", "daily_urgent": [sample_urgent_item]})
        write_phase4(
            "pending-replies.yaml",
            {"generated_at": "2026-03-23T08:30:00", "pending_replies": [sample_pending_item]},
        )
        write_phase4("sla-risks.yaml", {"generated_at": "2026-03-23T08:30:00", "sla_risks": [sample_sla_item]})

        assert main(["digest", "daily"]) == 0
        out = capsys.readouterr().out

        assert out.startswith("# 每日摘要\n")
        assert "## 紧急事项" in out
        assert "## 待回复" in out
        assert "## SLA 风险" in out
        assert "=" * 40 not in out

    def test_digest_pulse_missing_file_exits_1(self, phase4_root):
        assert main(["digest", "pulse", "--json"]) == 1

    def test_digest_pulse_json_schema(self, phase4_root, capsys):
        (phase4_root / "activity-pulse.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-24T10:00:00+08:00",
                    "notify_payload": {
                        "generated_at": "2026-03-24T10:00:00+08:00",
                        "stale": False,
                        "urgent_top_k": [],
                        "pending_count": 0,
                        "summary": "none",
                    },
                    "notifiable_items": [],
                    "recent_activity": [],
                    "needs_attention": [],
                    "thread_index": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        assert main(["digest", "pulse", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["digest_type"] == "pulse"
        assert "notify_payload" in payload

    def test_digest_pulse_human_output_uses_markdown_sections(self, phase4_root, capsys):
        (phase4_root / "activity-pulse.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-24T10:00:00+08:00",
                    "notify_payload": {
                        "generated_at": "2026-03-24T10:00:00+08:00",
                        "stale": False,
                        "urgent_top_k": [],
                        "pending_count": 1,
                        "summary": "有 1 条需要关注",
                    },
                    "notifiable_items": [{"thread_key": "项目A", "why": "等待你确认"}],
                    "recent_activity": [],
                    "needs_attention": [],
                    "thread_index": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        assert main(["digest", "pulse"]) == 0
        out = capsys.readouterr().out

        assert out.startswith("# 日内脉冲\n")
        assert "## 概览" in out
        assert "## 待推送线程" in out
        assert "=" * 40 not in out

    def test_digest_weekly_missing_file_exits_1(self, phase4_root):
        assert main(["digest", "weekly", "--json"]) == 1

    def test_digest_weekly_human_output_renders_full_markdown_sections(self, phase4_root, capsys):
        (phase4_root / "weekly-brief-raw.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-24T10:00:00+08:00",
                    "weekly_brief": {
                        "period": "2026-03-18 ~ 2026-03-24",
                        "total_threads_in_window": 12,
                        "material_summary": {
                            "sources": ["周会纪要"],
                            "period_hint": "上周",
                            "table_headers": ["项目", "状态"],
                            "row_count": 2,
                            "column_stats": [{"column": "状态", "summary": "1 个阻塞, 1 个推进中"}],
                            "open_risks": ["审批仍待确认"],
                            "notes": "材料来自周会纪要",
                        },
                        "flow_summary": [
                            {"flow": "deploy", "name": "部署", "count": 3, "highlight": "审批链条仍是主要阻塞"}
                        ],
                        "action_now": [
                            {"thread_key": "项目A", "flow": "deploy", "why": "今天要确认", "action": "回复审批意见"}
                        ],
                        "backlog": [
                            {"thread_key": "项目B", "flow": "support", "why": "仍需跟进", "next_step": "周三前追问供应商"}
                        ],
                        "important_changes": [
                            {"thread_key": "项目C", "change": "需求已确认", "impact": "可进入部署"}
                        ],
                        "top_actions": ["回复项目A", "跟进项目B"],
                        "rhythm_observation": "本周上午审批类线程明显增多。",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        assert main(["digest", "weekly"]) == 0
        out = capsys.readouterr().out

        assert out.startswith("# 每周简报\n")
        assert "## Action Now" in out
        assert "## Backlog" in out
        assert "## Important Changes" in out
        assert "## Flow Summary" in out
        assert "## Material Summary" in out
        assert "## Rhythm Observation" in out
        assert "=" * 40 not in out

    def test_thread_inspect_not_found_exits_1(self, phase4_root):
        assert main(["thread", "inspect", "missing-thread", "--json"]) == 1

    def test_thread_inspect_found_returns_full_contract(self, write_phase4, capsys):
        """thread inspect JSON must include all ThreadCard contract fields."""
        write_phase4("daily-urgent.yaml", {
            "generated_at": "2026-03-23T08:30:00",
            "daily_urgent": [{
                "thread_key": "thread-xyz",
                "why": "Ping",
                "urgency_score": 40,
                "stage": "open",
                "waiting_on": "customer",
                "flow": "support",
            }],
        })
        assert main(["thread", "inspect", "thread-xyz", "--json"]) == 0
        body = json.loads(capsys.readouterr().out)
        required = {"thread_id", "state", "waiting_on", "confidence",
                    "evidence_refs", "context_refs", "why"}
        missing = required - body.keys()
        assert not missing, f"ThreadCard contract fields missing: {missing}"
        assert body["thread_id"] == "thread-xyz"

    def test_thread_inspect_falls_back_to_context_and_returns_content_excerpt(self, phase4_root, capsys):
        state_root = phase4_root.parents[2]
        phase3_dir = state_root / "runtime" / "validation" / "phase-3"
        phase3_dir.mkdir(parents=True, exist_ok=True)
        (phase3_dir / "context-pack.json").write_text(
            json.dumps(
                {
                    "top_threads": [
                        {
                            "thread_key": "【部署资源申请】广东aq-mbzk-v0.9.3部署资源申请",
                            "latest_date": "2026-03-25T15:00:00+08:00",
                            "latest_subject": "Re: 答复：【部署资源申请】广东AQ-MBZK-V0.9.3部署资源申请",
                            "body_excerpt": "From: sczhang24@example.com\nSubject: Re: 答复：【部署资源申请】广东AQ-MBZK-V0.9.3部署资源申请",
                            "participants": ["sczhang24@example.com", "yangli73@example.com"],
                            "recipient_role": "group_only",
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        (phase4_root / "activity-pulse.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-25T15:05:00+08:00",
                    "notifiable_items": [],
                    "recent_activity": [],
                    "needs_attention": [],
                    "thread_index": [
                        {
                            "thread_key": "【部署资源申请】广东aq-mbzk-v0.9.3部署资源申请",
                            "latest_subject": "Re: 答复：【部署资源申请】广东AQ-MBZK-V0.9.3部署资源申请",
                            "last_activity_at": "2026-03-25T15:00:00+08:00",
                            "latest_message_ref": "INBOX#1752733651",
                            "new_message_count": 4,
                            "message_count": 4,
                            "unread_count": 3,
                            "queue_tags": [],
                            "why": "最近24小时新增 4 封邮件",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        context_dir = state_root / "runtime" / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        (context_dir / "phase1-context.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-25T15:05:00+08:00",
                    "lookback_days": 7,
                    "owner_domain": "example.com",
                    "envelopes": [
                        {
                            "id": "1752733651",
                            "subject": "Re: 答复：【部署资源申请】广东AQ-MBZK-V0.9.3部署资源申请",
                            "date": "2026-03-25 15:00+08:00",
                            "flags": [],
                        }
                    ],
                    "sampled_bodies": {
                        "1752733651": {
                            "subject": "Re: 答复：【部署资源申请】广东AQ-MBZK-V0.9.3部署资源申请",
                            "body": "From: sczhang24@example.com\nSubject: Re: 答复：【部署资源申请】广东AQ-MBZK-V0.9.3部署资源申请\n\nMBZK-V0.9.2版本：http://artifact.example/v092\nMBZK-V0.9.3版本：http://artifact.example/v093",
                        }
                    },
                    "stats": {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        assert main(["thread", "inspect", "【部署资源申请】广东aq-mbzk-v0.9.3部署资源申请", "--json"]) == 0
        body = json.loads(capsys.readouterr().out)
        assert body["thread_id"] == "【部署资源申请】广东aq-mbzk-v0.9.3部署资源申请"
        assert body["last_activity_at"] == "2026-03-25T15:00:00+08:00"
        assert body["latest_subject"] == "Re: 答复：【部署资源申请】广东AQ-MBZK-V0.9.3部署资源申请"
        assert body["latest_message_ref"] == "INBOX#1752733651"
        assert body["unread_count"] == 3
        assert "MBZK-V0.9.3版本" in body["content_excerpt"]

    def test_thread_progress_searches_activity_pulse(self, phase4_root, capsys):
        (phase4_root / "activity-pulse.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-24T10:00:00+08:00",
                    "notifiable_items": [],
                    "recent_activity": [],
                    "needs_attention": [],
                    "thread_index": [
                        {
                            "thread_key": "宁夏fdz现场国化资源申请",
                            "latest_subject": "宁夏fdz现场国化资源申请",
                            "last_activity_at": "2026-03-24T09:30:00+08:00",
                            "latest_message_ref": "INBOX#1",
                            "new_message_count": 1,
                            "message_count": 1,
                            "queue_tags": ["pending"],
                            "waiting_on": "me",
                            "flow": "delivery",
                            "stage": "open",
                            "why": "等待资源确认",
                            "fingerprint": "INBOX#1|pending",
                            "query_terms": ["宁夏", "资源申请"],
                            "score": 50,
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        assert main(["thread", "progress", "宁夏", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload[0]["thread_key"] == "宁夏fdz现场国化资源申请"


class TestOnboardingCli:
    """Onboarding flow should support start/status/advance with persisted state."""

    def test_onboarding_start_initializes_mailbox_stage(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))

        assert main(["onboarding", "start", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["stage"] == "mailbox_login"
        assert "邮箱" in payload["prompt"]

    def test_onboarding_next_advances_stage_and_marks_completed(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))

        assert main(["onboarding", "start", "--json"]) == 0
        _ = capsys.readouterr()

        assert main(["onboarding", "next", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["completed_stage"] == "mailbox_login"
        assert payload["current_stage"] == "llm_setup"
        assert "mailbox_login" in payload["completed_stages"]

    def test_onboarding_next_without_start_bootstraps_and_advances(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))

        assert main(["onboarding", "next", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["completed_stage"] == "mailbox_login"
        assert payload["current_stage"] == "llm_setup"
        assert "mailbox_login" in payload["completed_stages"]

    def test_onboarding_status_json_contract(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))

        assert main(["onboarding", "start", "--json"]) == 0
        _ = capsys.readouterr()

        assert main(["onboarding", "status", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)

        assert payload["current_stage"] == "mailbox_login"
        assert isinstance(payload["completed_stages"], list)
        assert "started_at" in payload
        assert "updated_at" in payload

    def test_onboard_openclaw_routes_to_wizard(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))

        class _FakeReport:
            ok = True

            def to_json_dict(self):
                return {"ok": True, "next_action": "continue in twinbox agent"}

        def fake_run_openclaw_onboard_v2(**kwargs):
            assert kwargs["dry_run"] is False
            return _FakeReport()

        monkeypatch.setattr(
            "twinbox_core.openclaw_onboard.run_openclaw_onboard_v2",
            fake_run_openclaw_onboard_v2,
        )

        assert main(["onboard", "openclaw", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["next_action"] == "continue in twinbox agent"

    def test_onboard_openclaw_v2_alias_routes_to_same_journey_shell(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))

        class _FakeReport:
            ok = True

            def to_json_dict(self):
                return {"ok": True, "next_action": "continue in twinbox agent"}

        def fake_run_openclaw_onboard_v2(**kwargs):
            assert kwargs["dry_run"] is False
            return _FakeReport()

        monkeypatch.setattr(
            "twinbox_core.openclaw_onboard.run_openclaw_onboard_v2",
            fake_run_openclaw_onboard_v2,
        )

        assert main(["onboard", "openclaw-v2", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["next_action"] == "continue in twinbox agent"

    def test_onboarding_status_text_feels_like_continuous_journey(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
        monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))

        assert main(["onboarding", "start"]) == 0
        out = capsys.readouterr().out

        assert "Journey" in out
        assert "Phase 2 of 2" in out


class TestMailboxCli:
    """Mailbox preflight routing and JSON passthrough."""

    def test_mailbox_preflight_json_route(self, monkeypatch, capsys):
        def fake_run_preflight(**kwargs):
            return 0, {
                "login_stage": "mailbox-connected",
                "status": "warn",
                "checks": {
                    "env": {"status": "success"},
                    "config_render": {"status": "success"},
                    "imap": {"status": "success"},
                    "smtp": {"status": "warn", "error_code": "smtp_skipped_read_only"},
                },
                "missing_env": [],
                "defaults_applied": {"MAIL_ACCOUNT_NAME": "myTwinbox"},
                "actionable_hint": "Mailbox read-only preflight passed.",
                "next_action": "Run phase1.",
            }

        monkeypatch.setattr("twinbox_core.mailbox.run_preflight", fake_run_preflight)

        assert main(["mailbox", "preflight", "--json"]) == 0
        body = json.loads(capsys.readouterr().out)
        assert body["login_stage"] == "mailbox-connected"
        assert body["checks"]["smtp"]["error_code"] == "smtp_skipped_read_only"

    def test_mailbox_preflight_text_route(self, monkeypatch, capsys):
        def fake_run_preflight(**kwargs):
            return 2, {
                "login_stage": "unconfigured",
                "status": "fail",
                "checks": {
                    "env": {"status": "fail", "fix_commands": ["export MAIL_ADDRESS=user@example.com"]},
                    "config_render": {"status": "skipped"},
                    "imap": {"status": "skipped"},
                    "smtp": {"status": "warn", "error_code": "smtp_skipped_read_only"},
                },
                "missing_env": ["MAIL_ADDRESS"],
                "defaults_applied": {},
                "actionable_hint": "Provide the missing mailbox settings before validating the account.",
                "next_action": "Set env and rerun.",
            }

        monkeypatch.setattr("twinbox_core.mailbox.run_preflight", fake_run_preflight)

        assert main(["mailbox", "preflight"]) == 2
        out = capsys.readouterr().out
        assert "Mailbox Preflight" in out
        assert "missing_env: MAIL_ADDRESS" in out


class TestTaskRoutes:
    """Thin task routes should wrap existing Twinbox views without adding new inference."""

    def test_task_latest_mail_json_wraps_activity_pulse(self, phase4_root, capsys):
        (phase4_root / "activity-pulse.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-24T10:00:00+08:00",
                    "notify_payload": {
                        "generated_at": "2026-03-24T10:00:00+08:00",
                        "stale": False,
                        "urgent_top_k": [
                            {"thread_key": "项目A资源申请", "why": "等待资源确认"},
                        ],
                        "pending_count": 2,
                        "summary": "2 条线程需要关注",
                    },
                    "notifiable_items": [],
                    "recent_activity": [{"thread_key": "项目A资源申请"}],
                    "needs_attention": [{"thread_key": "项目B上线"}],
                    "thread_index": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        assert main(["task", "latest-mail", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["task"] == "latest-mail"
        assert payload["summary"] == "2 条线程需要关注"
        assert payload["urgent_top_k"][0]["thread_key"] == "项目A资源申请"

    def test_task_latest_mail_unread_only_filters_and_rewrites_summary(self, phase4_root, capsys):
        (phase4_root / "activity-pulse.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-24T10:00:00+08:00",
                    "notify_payload": {
                        "generated_at": "2026-03-24T10:00:00+08:00",
                        "stale": False,
                        "urgent_top_k": [
                            {"thread_key": "unread-urgent", "why": "x", "unread_count": 1},
                            {"thread_key": "read-urgent", "why": "y", "unread_count": 0},
                        ],
                        "pending_count": 2,
                        "summary": "推送摘要三条",
                    },
                    "notifiable_items": [],
                    "recent_activity": [
                        {"thread_key": "unread-recent", "unread_count": 2},
                        {"thread_key": "read-recent", "unread_count": 0},
                    ],
                    "needs_attention": [
                        {"thread_key": "unread-attn", "unread_count": 1},
                    ],
                    "thread_index": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        assert main(["task", "latest-mail", "--unread-only", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["unread_only"] is True
        assert [i["thread_key"] for i in payload["urgent_top_k"]] == ["unread-urgent"]
        assert [i["thread_key"] for i in payload["recent_activity"]] == ["unread-recent"]
        assert [i["thread_key"] for i in payload["needs_attention"]] == ["unread-attn"]
        assert "未读视图" in payload["summary"]
        assert "推送摘要三条" in payload["summary"]
        assert payload["notify_payload"]["summary"] == payload["summary"]
        assert payload["notify_payload"]["unread_only"] is True

    def test_task_todo_json_wraps_existing_queue_views(self, write_phase4, capsys):
        write_phase4("daily-urgent.yaml", {
            "generated_at": "2026-03-23T08:30:00",
            "daily_urgent": [{
                "thread_key": "thread-urgent",
                "why": "Customer escalation requires response",
                "reason_code": "escalation",
                "urgency_score": 85,
                "action_hint": "please reply",
                "flow": "support",
                "stage": "escalated",
                "waiting_on": "me",
                "evidence_source": "envelope-5",
            }],
        })
        write_phase4("pending-replies.yaml", {
            "generated_at": "2026-03-23T08:30:00",
            "pending_replies": [{
                "thread_key": "thread-pending",
                "why": "Awaiting response from customer",
                "waiting_on_me": True,
                "flow": "project",
                "evidence_source": "envelope-8",
            }],
        })
        assert main(["task", "todo", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["task"] == "todo"
        assert payload["urgent"]["items"][0]["thread_id"] == "thread-urgent"
        assert payload["pending"]["items"][0]["thread_id"] == "thread-pending"

    def test_task_todo_json_marks_cc_only_threads(self, write_phase4, capsys):
        write_phase4("daily-urgent.yaml", {
            "generated_at": "2026-03-23T08:30:00",
            "daily_urgent": [{
                "thread_key": "thread-urgent-cc",
                "why": "仅抄送但被错误拉高",
                "reason_code": "cc_watch",
                "urgency_score": 54,
                "action_hint": "monitor only",
                "flow": "support",
                "stage": "watch",
                "waiting_on": "owner",
                "evidence_source": "envelope-cc-1",
                "recipient_role": "cc_only",
            }],
        })
        write_phase4("pending-replies.yaml", {
            "generated_at": "2026-03-23T08:30:00",
            "pending_replies": [{
                "thread_key": "thread-pending-cc",
                "why": "仅抄送，先确认是否真要我回复",
                "waiting_on_me": True,
                "flow": "project",
                "evidence_source": "envelope-cc-2",
                "recipient_role": "cc_only",
            }],
        })
        assert main(["task", "todo", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["urgent"]["items"][0]["thread_id"] == "[CC] thread-urgent-cc"
        assert payload["pending"]["items"][0]["thread_id"] == "[CC] thread-pending-cc"

    def test_task_todo_json_marks_group_only_threads(self, write_phase4, capsys):
        write_phase4("daily-urgent.yaml", {
            "generated_at": "2026-03-23T08:30:00",
            "daily_urgent": [{
                "thread_key": "thread-urgent-group",
                "why": "通过邮件组收到",
                "reason_code": "group_watch",
                "urgency_score": 80,
                "action_hint": "review context",
                "flow": "project",
                "stage": "coordination",
                "waiting_on": "vendor",
                "evidence_source": "envelope-group-1",
                "recipient_role": "group_only",
            }],
        })
        write_phase4("pending-replies.yaml", {
            "generated_at": "2026-03-23T08:30:00",
            "pending_replies": [{
                "thread_key": "thread-pending-group",
                "why": "邮件组里有人点名需要确认",
                "waiting_on_me": True,
                "flow": "project",
                "evidence_source": "envelope-group-2",
                "recipient_role": "group_only",
            }],
        })
        assert main(["task", "todo", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["urgent"]["items"][0]["thread_id"] == "[GRP] thread-urgent-group"
        assert payload["pending"]["items"][0]["thread_id"] == "[GRP] thread-pending-group"

    def test_task_progress_json_wraps_thread_progress(self, phase4_root, capsys):
        (phase4_root / "activity-pulse.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-24T10:00:00+08:00",
                    "notifiable_items": [],
                    "recent_activity": [],
                    "needs_attention": [],
                    "thread_index": [
                        {
                            "thread_key": "宁夏fdz现场国化资源申请",
                            "latest_subject": "宁夏fdz现场国化资源申请",
                            "last_activity_at": "2026-03-24T09:30:00+08:00",
                            "latest_message_ref": "INBOX#1",
                            "new_message_count": 1,
                            "message_count": 1,
                            "queue_tags": ["pending"],
                            "waiting_on": "me",
                            "flow": "delivery",
                            "stage": "open",
                            "why": "等待资源确认",
                            "fingerprint": "INBOX#1|pending",
                            "query_terms": ["宁夏", "资源申请"],
                            "score": 50,
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        assert main(["task", "progress", "宁夏", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["task"] == "progress"
        assert payload["matches"][0]["thread_key"] == "宁夏fdz现场国化资源申请"

    def test_task_progress_json_exposes_group_recipient_role(self, phase4_root, capsys):
        phase3_dir = phase4_root.parent / "phase-3"
        phase3_dir.mkdir(parents=True, exist_ok=True)
        (phase3_dir / "context-pack.json").write_text(
            json.dumps(
                {
                    "top_threads": [
                        {
                            "thread_key": "宁夏fdz现场国化资源申请",
                            "recipient_role": "group_only",
                        }
                    ]
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (phase4_root / "activity-pulse.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-24T10:00:00+08:00",
                    "notifiable_items": [],
                    "recent_activity": [],
                    "needs_attention": [],
                    "thread_index": [
                        {
                            "thread_key": "宁夏fdz现场国化资源申请",
                            "latest_subject": "宁夏fdz现场国化资源申请",
                            "last_activity_at": "2026-03-24T09:30:00+08:00",
                            "latest_message_ref": "INBOX#1",
                            "new_message_count": 1,
                            "message_count": 1,
                            "queue_tags": ["pending"],
                            "waiting_on": "me",
                            "flow": "delivery",
                            "stage": "open",
                            "why": "等待资源确认",
                            "fingerprint": "INBOX#1|pending",
                            "query_terms": ["宁夏", "资源申请"],
                            "score": 50,
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        assert main(["task", "progress", "宁夏", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["matches"][0]["recipient_role"] == "group_only"
        assert payload["matches"][0]["thread_key_display"] == "[GRP] 宁夏fdz现场国化资源申请"

    def test_task_mailbox_status_wraps_preflight(self, monkeypatch, capsys):
        seen_kwargs = {}

        def fake_run_preflight(*, state_root=None, env=None, account_override="", folder="INBOX", page_size=5):
            seen_kwargs.update(
                {
                    "state_root": state_root,
                    "env": env,
                    "account_override": account_override,
                    "folder": folder,
                    "page_size": page_size,
                }
            )
            return 0, {
                "login_stage": "mailbox-connected",
                "status": "warn",
                "checks": {
                    "env": {"status": "success"},
                    "config_render": {"status": "success"},
                    "imap": {"status": "success"},
                    "smtp": {"status": "warn", "error_code": "smtp_skipped_read_only"},
                },
                "missing_env": [],
                "defaults_applied": {"MAIL_ACCOUNT_NAME": "myTwinbox"},
                "actionable_hint": "Mailbox read-only preflight passed.",
                "next_action": "Run phase1.",
            }

        monkeypatch.setattr("twinbox_core.mailbox.run_preflight", fake_run_preflight)
        assert main(["task", "mailbox-status", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["task"] == "mailbox-status"
        assert payload["login_stage"] == "mailbox-connected"
        assert seen_kwargs["account_override"] == ""


def test_task_cli_fresh_import_avoids_heavy_submodules() -> None:
    """Fresh interpreter: loading task_cli must not import mailbox / deploy / daytime_slice."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    src = str(repo_root / "src")
    env = os.environ.copy()
    extra = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not extra else src + os.pathsep + extra
    code = (
        "import sys\n"
        "import twinbox_core.task_cli\n"
        "heavy = ('twinbox_core.mailbox', 'twinbox_core.openclaw_deploy', 'twinbox_core.daytime_slice')\n"
        "loaded = [n for n in heavy if n in sys.modules]\n"
        "assert not loaded, loaded\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
