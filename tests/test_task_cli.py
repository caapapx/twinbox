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

    def test_digest_daily_json_schema(self, phase4_root, capsys):
        """Daily digest JSON must include digest_type, sections, generated_at, stale."""
        assert main(["digest", "daily", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        for field in ("digest_type", "sections", "generated_at", "stale"):
            assert field in payload, f"Missing field: {field}"
        assert payload["digest_type"] == "daily"
        assert isinstance(payload["sections"], dict)

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

    def test_digest_weekly_missing_file_exits_1(self, phase4_root):
        assert main(["digest", "weekly", "--json"]) == 1

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

        monkeypatch.setattr("twinbox_core.task_cli.run_preflight", fake_run_preflight)

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

        monkeypatch.setattr("twinbox_core.task_cli.run_preflight", fake_run_preflight)

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

    def test_task_mailbox_status_wraps_preflight(self, monkeypatch, capsys):
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

        monkeypatch.setattr("twinbox_core.task_cli.run_preflight", fake_run_preflight)
        assert main(["task", "mailbox-status", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["task"] == "mailbox-status"
        assert payload["login_stage"] == "mailbox-connected"
