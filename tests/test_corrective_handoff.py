"""End-to-end local corrective handoff without mailbox side effects."""
from __future__ import annotations

from twinbox_core.classification_store import case_ref, load_classifications, publish_classifications
from twinbox_core.evidence_contract import SourceGrant
from twinbox_core.feedback import process_feedback


def _payload(ref, revision, decision_id, kind, decision):
    return {
        "schema_version": "1.0", "decision_id": decision_id, "scope_id": "scope-a",
        "case_ref": ref, "expected_revision": revision, "actor_ref": "owner-a",
        "kind": kind, "evidence_refs": ["m1:e1"], "decision": decision,
    }


def test_propose_confirm_then_receipt_preserves_business_state(tmp_path):
    publish_classifications(
        tmp_path, scope_id="scope-a",
        cases=[{"case_key": "c1", "mail_refs": ["m1"], "evidence_refs": ["m1:e1"]}],
        classifications=[{"case_key": "c1", "status": "classified", "primary_event_type": "approval"}],
        coverage={"state": "complete"}, pack_fingerprint="p1", classifier_version="c1", source_revision=1,
    )
    ref = case_ref("scope-a", "c1")
    grant = SourceGrant(scope_id="scope-a", account_ref="a", evidence_refs=frozenset({"m1:e1"}), enabled=True)
    kinds = {"correction_proposal", "human_confirmation", "execution_receipt"}

    proposal = process_feedback(tmp_path, _payload(ref, 1, "d1", "correction_proposal", {
        "field": "primary_event_type", "proposed_values": ["review"], "reason": "Needs owner review.",
    }), grant=grant, actor_ref="owner-a", allowed_kinds=kinds)
    assert proposal["status"] == "accepted" and proposal["applied"] is False
    assert load_classifications(tmp_path, "scope-a")["revision"] == 1

    confirmation = process_feedback(tmp_path, _payload(ref, 1, "d2", "human_confirmation", {
        "confirmation": "responsibility_confirmed", "reason": "Owner confirmed.",
    }), grant=grant, actor_ref="owner-a", allowed_kinds=kinds)
    assert confirmation["classification_revision"] == 2

    stale_receipt = process_feedback(tmp_path, _payload(ref, 1, "d3", "execution_receipt", {
        "run_ref": "run-old", "outcome": "succeeded", "occurred_at": "2026-09-20T12:00:00+08:00",
    }), grant=grant, actor_ref="owner-a", allowed_kinds=kinds)
    assert stale_receipt["status"] == "conflict"

    receipt = process_feedback(tmp_path, _payload(ref, 2, "d4", "execution_receipt", {
        "run_ref": "run-new", "outcome": "succeeded", "occurred_at": "2026-09-20T12:01:00+08:00",
    }), grant=grant, actor_ref="owner-a", allowed_kinds=kinds)
    assert receipt["status"] == "accepted" and receipt["business_done"] is False
    current = load_classifications(tmp_path, "scope-a")
    assert current["revision"] == 2
    assert current["active_snapshot"]["classifications"][0]["status"] == "classified"
