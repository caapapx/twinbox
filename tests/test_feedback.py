"""Reverse feedback is authorized, idempotent and never implies business completion."""
from __future__ import annotations

import copy
import json

import pytest

from twinbox_core.classification_store import case_ref, load_classifications, publish_classifications
from twinbox_core.evidence_contract import SourceGrant


def _seed(root):
    published = publish_classifications(
        root,
        scope_id="scope-a",
        cases=[{"case_key": "mail-1", "mail_refs": ["mail-1"], "evidence_refs": ["mail-1:excerpt-1"]}],
        classifications=[{
            "case_key": "mail-1",
            "status": "classified",
            "primary_event_type": "approval",
            "tags": {"project": ["alpha"]},
        }],
        coverage={"state": "complete"},
        pack_fingerprint="pack-1",
        classifier_version="classifier-1",
        source_revision=1,
    )
    return published, case_ref("scope-a", "mail-1")


def _grant():
    return SourceGrant(
        scope_id="scope-a",
        account_ref="account-a",
        evidence_refs=frozenset({"mail-1:excerpt-1"}),
        enabled=True,
    )


def _payload(case, revision=1, *, decision_id="decision-1", kind="correction_proposal"):
    decisions = {
        "correction_proposal": {
            "field": "primary_event_type",
            "proposed_values": ["review"],
            "reason": "The evidence describes a review rather than an approval.",
        },
        "human_confirmation": {
            "confirmation": "responsibility_confirmed",
            "reason": "The business owner confirmed responsibility.",
        },
        "execution_receipt": {
            "run_ref": "run-1",
            "outcome": "succeeded",
            "occurred_at": "2026-09-20T12:00:00+08:00",
        },
    }
    return {
        "schema_version": "1.0",
        "decision_id": decision_id,
        "scope_id": "scope-a",
        "case_ref": case,
        "expected_revision": revision,
        "actor_ref": "reviewer-a",
        "kind": kind,
        "evidence_refs": ["mail-1:excerpt-1"],
        "decision": decisions[kind],
    }


def _process(root, payload, *, kinds=None, actor="reviewer-a"):
    from twinbox_core.feedback import process_feedback

    return process_feedback(
        root,
        payload,
        grant=_grant(),
        actor_ref=actor,
        allowed_kinds=kinds or {payload["kind"]},
    )


def test_authorization_is_rechecked_before_persisting(tmp_path):
    from twinbox_core.feedback import FeedbackStoreError, feedback_path

    _, case = _seed(tmp_path)
    with pytest.raises(FeedbackStoreError, match="actor_mismatch"):
        _process(tmp_path, _payload(case), actor="different-actor")
    assert not feedback_path(tmp_path).exists()


def test_same_decision_is_idempotent_but_changed_payload_is_rejected(tmp_path):
    from twinbox_core.feedback import FeedbackStoreError

    _, case = _seed(tmp_path)
    payload = _payload(case)
    first = _process(tmp_path, payload)
    second = _process(tmp_path, payload)
    assert first == second

    changed = copy.deepcopy(payload)
    changed["decision"]["reason"] = "A different correction using the same decision id."
    with pytest.raises(FeedbackStoreError, match="decision_id_conflict"):
        _process(tmp_path, changed)

    audit = (tmp_path / "runtime/context/feedback-audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(audit) == 1


def test_out_of_order_or_unknown_case_becomes_conflict(tmp_path):
    _, case = _seed(tmp_path)
    stale = _process(tmp_path, _payload(case, revision=2))
    assert stale["status"] == "conflict"
    assert stale["reason"] == "revision_conflict"

    unknown = _process(tmp_path, _payload("case_unknown", decision_id="decision-2"))
    assert unknown["status"] == "conflict"
    assert unknown["reason"] == "case_not_found"


def test_human_confirmation_updates_overlay_and_rejects_old_revision(tmp_path):
    _, case = _seed(tmp_path)
    confirmed = _process(tmp_path, _payload(case, kind="human_confirmation"))
    assert confirmed["status"] == "accepted"
    assert confirmed["classification_revision"] == 2

    current = load_classifications(tmp_path, "scope-a")
    stored_case = current["active_snapshot"]["cases"][0]
    assert stored_case["human_confirmation"]["actor_ref"] == "reviewer-a"
    assert stored_case["human_confirmation"]["confirmation"] == "responsibility_confirmed"

    late = _process(tmp_path, _payload(case, revision=1, decision_id="decision-late"))
    assert late["status"] == "conflict"
    assert late["reason"] == "revision_conflict"


def test_execution_receipt_is_observation_not_business_done(tmp_path):
    _, case = _seed(tmp_path)
    receipt = _process(tmp_path, _payload(case, kind="execution_receipt"))
    assert receipt["status"] == "accepted"
    assert receipt["business_done"] is False
    assert receipt["observation"]["outcome"] == "succeeded"

    classification = load_classifications(tmp_path, "scope-a")
    assert classification["revision"] == 1
    row = classification["active_snapshot"]["classifications"][0]
    assert row["status"] == "classified"
    assert "done" not in json.dumps(classification).lower()


def test_cli_uses_local_source_grant_not_payload_authority(tmp_path, monkeypatch):
    from twinbox_core import cli

    _, case = _seed(tmp_path)
    grant_path = tmp_path / "config/source-grant.json"
    grant_path.parent.mkdir(parents=True)
    grant_path.write_text(json.dumps({
        "schema_version": "1.0",
        "enabled": True,
        "scope_id": "scope-a",
        "account_ref": "account-a",
        "mail_refs": ["mail-1"],
        "evidence_refs": ["mail-1:excerpt-1"],
        "actors": {"reviewer-a": ["correction_proposal"]},
    }), encoding="utf-8")
    monkeypatch.setattr(cli, "_account_root", lambda account_id=None: tmp_path)
    monkeypatch.setattr(cli, "_resolved_account_id", lambda account_id=None: "account-a")

    accepted = cli.cmd_feedback(["--payload-json", json.dumps(_payload(case))], account_id="account-a")
    assert accepted["ok"] is True
    denied_payload = _payload(case, decision_id="denied", kind="execution_receipt")
    denied = cli.cmd_feedback(["--payload-json", json.dumps(denied_payload)], account_id="account-a")
    assert denied["ok"] is False
    assert denied["error"] == "feedback_forbidden"
