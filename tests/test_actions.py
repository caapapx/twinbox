"""Confirmation-token state-machine tests; all state is local and dry-run."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from twinbox_core.actions import scan_proposals, review_proposal


def _now() -> datetime:
    return datetime.fromisoformat("2026-09-20T09:00:00+08:00")


def _seed_state(root: Path, *, why: str = "请登记") -> None:
    pulse = root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
    pulse.parent.mkdir(parents=True)
    pulse.write_text(
        json.dumps(
            {
                "needs_attention": [
                    {
                        "thread_key": "验收",
                        "projection": "action_required",
                        "latest_message_ref": "INBOX#1",
                        "why": why,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    packs = root / "packs"
    packs.mkdir()
    (packs / "user.yaml").write_text(
        """id: user
version: '1'
action_policy:
- id: notify-approval
  enabled: true
  action_type: notify
  target_scope: [owner]
  require_projection: action_required
""",
        encoding="utf-8",
    )


def _stored_proposal(root: Path) -> dict[str, object]:
    return json.loads((root / "runtime" / "actions" / "proposals.json").read_text(encoding="utf-8"))["proposals"][0]


def _audit_events(root: Path) -> list[dict[str, object]]:
    path = root / "runtime" / "audit" / "actions.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_issues_short_lived_human_confirmation_token_and_stops_agent_turn(tmp_path: Path) -> None:
    _seed_state(tmp_path)

    result = scan_proposals(tmp_path, now=_now())

    assert result["created"] == 1
    proposal = result["proposals"][0]
    assert proposal["status"] == "awaiting_confirmation"
    assert proposal["draft_payload"]["schema_version"] == "twinbox.action-draft.v1"
    assert proposal["draft_payload_hash"]
    card = proposal["card_payload"]
    token = card["confirmation"]["token"]
    assert token.startswith("ctk_")
    assert card["confirmation"]["expires_at"] == "2026-09-20T09:05:00+08:00"
    assert card["interaction"] == {
        "human_confirmation_required": True,
        "must_stop_agent_turn": True,
        "same_turn_confirmation_forbidden": True,
    }

    stored = _stored_proposal(tmp_path)
    assert stored["confirmation"]["token_hash"] != token
    assert stored["confirmation"]["token_state"] == "issued"
    assert all(event["event"] in {"draft_created", "confirmation_issued"} for event in _audit_events(tmp_path))


def test_confirm_requires_token_is_single_use_and_never_executes(tmp_path: Path) -> None:
    _seed_state(tmp_path)
    proposal = scan_proposals(tmp_path, now=_now())["proposals"][0]
    token = proposal["card_payload"]["confirmation"]["token"]

    missing = review_proposal(tmp_path, proposal["proposal_id"], "confirm", now=_now())
    assert missing == {
        "ok": False,
        "error": "confirmation token required",
        "code": "confirmation_token_required",
    }
    assert _stored_proposal(tmp_path)["status"] == "awaiting_confirmation"

    confirmed = review_proposal(
        tmp_path, proposal["proposal_id"], "confirm", confirmation_token=token, now=_now() + timedelta(seconds=1)
    )
    assert confirmed["ok"] is True
    assert confirmed["proposal"]["status"] == "confirmed"
    assert confirmed["proposal"]["execution"] == {
        "status": "blocked_read_only",
        "reason": "Twinbox confirmation does not authorize mailbox or outbound execution",
    }

    replay = review_proposal(
        tmp_path, proposal["proposal_id"], "confirm", confirmation_token=token, now=_now() + timedelta(seconds=2)
    )
    assert replay == {
        "ok": False,
        "error": "proposal is not awaiting confirmation",
        "code": "invalid_proposal_state",
    }
    assert _stored_proposal(tmp_path)["status"] == "confirmed"
    assert all(event.get("status") != "executing" for event in _audit_events(tmp_path))


def test_token_expiry_and_payload_tamper_stop_confirmation(tmp_path: Path) -> None:
    _seed_state(tmp_path)
    proposal = scan_proposals(tmp_path, now=_now())["proposals"][0]
    token = proposal["card_payload"]["confirmation"]["token"]

    expired = review_proposal(
        tmp_path, proposal["proposal_id"], "confirm", confirmation_token=token, now=_now() + timedelta(minutes=5)
    )
    assert expired == {
        "ok": False,
        "error": "confirmation token expired",
        "code": "confirmation_token_expired",
    }
    assert _stored_proposal(tmp_path)["status"] == "expired"

    _seed_state(tmp_path / "tampered")
    tampered = scan_proposals(tmp_path / "tampered", now=_now())["proposals"][0]
    tampered_token = tampered["card_payload"]["confirmation"]["token"]
    path = tmp_path / "tampered" / "runtime" / "actions" / "proposals.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["proposals"][0]["draft_payload"]["summary"]["why"] = "attacker changed the reviewed draft"
    path.write_text(json.dumps(data), encoding="utf-8")

    invalid = review_proposal(
        tmp_path / "tampered", tampered["proposal_id"], "confirm", confirmation_token=tampered_token, now=_now()
    )
    assert invalid == {
        "ok": False,
        "error": "draft payload no longer matches its confirmation token",
        "code": "confirmation_payload_mismatch",
    }
    assert _stored_proposal(tmp_path / "tampered")["status"] == "expired"
    assert any(
        event["event"] == "confirmation_expired" and event["reason"] == "draft_payload_hash_mismatch"
        for event in _audit_events(tmp_path / "tampered")
    )


def test_changed_payload_expires_old_token_and_issues_a_new_one(tmp_path: Path) -> None:
    _seed_state(tmp_path, why="请登记")
    first = scan_proposals(tmp_path, now=_now())["proposals"][0]
    first_token = first["card_payload"]["confirmation"]["token"]

    pulse = tmp_path / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
    data = json.loads(pulse.read_text(encoding="utf-8"))
    data["needs_attention"][0]["why"] = "请在今天登记，风险升级"
    pulse.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    refreshed = scan_proposals(tmp_path, now=_now() + timedelta(seconds=1))["proposals"][0]
    fresh_token = refreshed["card_payload"]["confirmation"]["token"]

    assert refreshed["status"] == "awaiting_confirmation"
    assert fresh_token != first_token
    rejected_old = review_proposal(
        tmp_path, refreshed["proposal_id"], "confirm", confirmation_token=first_token, now=_now() + timedelta(seconds=2)
    )
    assert rejected_old == {
        "ok": False,
        "error": "confirmation token is invalid",
        "code": "confirmation_token_invalid",
    }
    assert _stored_proposal(tmp_path)["status"] == "awaiting_confirmation"
    assert any(
        event["event"] == "confirmation_expired" and event["reason"] == "draft_payload_changed"
        for event in _audit_events(tmp_path)
    )


def test_cli_passes_confirmation_token_and_reason_to_local_review(tmp_path: Path, monkeypatch, capsys) -> None:
    _seed_state(tmp_path)
    issued_now = datetime.now(ZoneInfo("Asia/Shanghai"))
    proposal = scan_proposals(tmp_path, now=issued_now)["proposals"][0]
    token = proposal["card_payload"]["confirmation"]["token"]

    import twinbox_core.cli as cli

    monkeypatch.setattr(cli, "_account_root", lambda account_id=None: tmp_path)
    exit_code = cli.main(
        [
            "actions",
            "review",
            proposal["proposal_id"],
            "confirm",
            "--confirmation-token",
            token,
            "--reason",
            "human approved after review",
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["proposal"]["status"] == "confirmed"
    assert payload["proposal"]["review_reason"] == "human approved after review"
