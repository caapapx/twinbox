from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from twinbox_core.classification_store import (
    ClassificationStoreError,
    case_ref,
    load_classifications,
    lookup_case,
    publish_classifications,
    tombstone_cases,
)


def _publish(root: Path, *, cases, classifications, **kwargs):
    return publish_classifications(
        root,
        scope_id=kwargs.pop("scope_id", "acct-a"),
        cases=cases,
        classifications=classifications,
        coverage=kwargs.pop("coverage", {"window": {"since": "2026-08-01", "until": "2026-09-20"}, "enumerated": 1}),
        pack_fingerprint=kwargs.pop("pack_fingerprint", "pack-v1"),
        classifier_version=kwargs.pop("classifier_version", "classifier-v1"),
        source_revision=kwargs.pop("source_revision", 1),
        observed_at=kwargs.pop("observed_at", "2026-09-20T10:00:00+08:00"),
        **kwargs,
    )


def test_one_mail_can_support_multiple_cases(tmp_path):
    result = _publish(
        tmp_path,
        cases=[
            {"case_key": "contract-review", "mail_refs": ["mail-1"], "evidence_refs": ["mail-1:e1"]},
            {"case_key": "payment-risk", "mail_refs": ["mail-1"], "evidence_refs": ["mail-1:e2"]},
        ],
        classifications=[
            {"case_key": "contract-review", "status": "classified", "primary_event_type": "contract.review"},
            {"case_key": "payment-risk", "status": "classified", "primary_event_type": "commercial.risk"},
        ],
    )
    assert len(result["active_snapshot"]["cases"]) == 2
    assert len({row["case_ref"] for row in result["active_snapshot"]["cases"]}) == 2


def test_same_subject_different_project_stays_separate(tmp_path):
    cases = [
        {"case_key": "review|project-a", "subject": "Review", "project_ref": "project-a", "mail_refs": ["m1"]},
        {"case_key": "review|project-b", "subject": "Review", "project_ref": "project-b", "mail_refs": ["m2"]},
    ]
    result = _publish(tmp_path, cases=cases, classifications=[])
    refs = [row["case_ref"] for row in result["active_snapshot"]["cases"]]
    assert refs[0] != refs[1]


def test_rule_version_switch_keeps_case_identity_and_confirmation(tmp_path):
    first = _publish(
        tmp_path,
        cases=[{"case_key": "c1", "mail_refs": ["m1"], "human_confirmation": {"actor_ref": "owner", "value": "approval"}}],
        classifications=[{"case_key": "c1", "status": "classified", "primary_event_type": "approval"}],
    )
    second = _publish(
        tmp_path,
        cases=[{"case_key": "c1", "mail_refs": ["m1"]}],
        classifications=[{"case_key": "c1", "status": "classified", "primary_event_type": "decision"}],
        pack_fingerprint="pack-v2",
        classifier_version="classifier-v2",
        source_revision=2,
        expected_revision=first["revision"],
    )
    assert second["active_snapshot"]["cases"][0]["case_ref"] == first["active_snapshot"]["cases"][0]["case_ref"]
    assert second["active_snapshot"]["cases"][0]["human_confirmation"]["value"] == "approval"
    assert second["active_snapshot"]["classifications"][0]["primary_event_type"] == "decision"


def test_uncovered_cross_month_case_is_unknown_not_negative(tmp_path):
    _publish(tmp_path, cases=[], classifications=[], coverage={"window": {"since": "2026-09-01", "until": "2026-09-20"}, "enumerated": 0})
    missing = lookup_case(tmp_path, "acct-a", case_ref("acct-a", "old-case"))
    assert missing == {"case_ref": case_ref("acct-a", "old-case"), "status": "unknown", "covered": False}


def test_tombstone_wins_over_cached_classification(tmp_path):
    first = _publish(
        tmp_path,
        cases=[{"case_key": "c1", "mail_refs": ["m1"]}],
        classifications=[{"case_key": "c1", "status": "classified", "primary_event_type": "approval"}],
    )
    ref = first["active_snapshot"]["cases"][0]["case_ref"]
    tombstone_cases(tmp_path, scope_id="acct-a", case_refs=[ref], expected_revision=first["revision"])
    found = lookup_case(tmp_path, "acct-a", ref)
    assert found["status"] == "tombstoned"
    assert "primary_event_type" not in found


def test_revision_conflict_does_not_overwrite(tmp_path):
    first = _publish(tmp_path, cases=[], classifications=[])
    with pytest.raises(ClassificationStoreError, match="revision_conflict"):
        _publish(tmp_path, cases=[], classifications=[], source_revision=2, expected_revision=0)
    assert load_classifications(tmp_path, "acct-a")["revision"] == first["revision"]


def test_same_source_revision_with_different_digest_conflicts(tmp_path):
    _publish(tmp_path, cases=[], classifications=[], source_digest="source-a")
    with pytest.raises(ClassificationStoreError, match="source_revision_conflict"):
        _publish(tmp_path, cases=[], classifications=[], source_digest="source-b")


def test_atomic_publish_failure_keeps_old_snapshot(tmp_path, monkeypatch):
    first = _publish(tmp_path, cases=[], classifications=[])
    old = json.dumps(first, sort_keys=True)
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        _publish(tmp_path, cases=[], classifications=[], source_revision=2, expected_revision=first["revision"])
    assert json.dumps(load_classifications(tmp_path, "acct-a"), sort_keys=True) == old


def test_account_state_roots_are_isolated(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    _publish(a, cases=[{"case_key": "c1", "mail_refs": ["m1"]}], classifications=[], scope_id="acct-a")
    assert load_classifications(b, "acct-b")["revision"] == 0
    assert load_classifications(a, "acct-a")["active_snapshot"]["cases"]


def test_event_extraction_publishes_lineage_and_preserves_manual_confirmation(tmp_path, monkeypatch):
    from twinbox_core import events
    from twinbox_core.pack import validate_pack
    from twinbox_core.pulse import write_activity_pulse

    pack = validate_pack({"id": "ops", "version": "1", "classification": {"event_types": [
        {"id": "approval", "when": {"subject_regex": "review"}}
    ]}})
    monkeypatch.setattr(events, "load_active_pack", lambda _: pack)
    context = {"source_account": "acct-a", "generated_at": "2026-09-20T09:00:00+08:00", "envelopes": [{
        "id": "7", "folder": "INBOX", "subject": "Review request",
        "date": "2026-09-20T08:00:00+08:00", "from_addr": "a@example.com",
    }]}
    raw = tmp_path / "runtime/validation/phase-1/raw/envelopes-merged.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps(context["envelopes"]), encoding="utf-8")
    events.extract_events(context, tmp_path)
    stored = load_classifications(tmp_path, "acct-a")
    ref = stored["active_snapshot"]["cases"][0]["case_ref"]

    # Simulate a prior authorized human layer, then rerun automatic extraction.
    stored["active_snapshot"]["cases"][0]["human_confirmation"] = {"actor_ref": "owner", "value": "approval"}
    from twinbox_core.classification_store import classification_path
    classification_path(tmp_path).write_text(json.dumps(stored), encoding="utf-8")
    before_revision = stored["revision"]
    before_observed = stored["active_snapshot"]["observed_at"]
    events.extract_events(context, tmp_path)
    after = load_classifications(tmp_path, "acct-a")
    assert after["active_snapshot"]["cases"][0]["case_ref"] == ref
    assert after["active_snapshot"]["cases"][0]["human_confirmation"]["actor_ref"] == "owner"

    pulse, _ = write_activity_pulse(tmp_path)
    assert pulse["classification_lineage"]["scope_id"] == "acct-a"
    assert pulse["classification_lineage"]["revision"] >= before_revision
    # Rebuilding a short-lived pulse must not republish or age the long-lived snapshot.
    unchanged = load_classifications(tmp_path, "acct-a")
    assert unchanged["revision"] == after["revision"]
    assert unchanged["active_snapshot"]["observed_at"] == after["active_snapshot"]["observed_at"]
    assert before_observed == after["active_snapshot"]["observed_at"]


def test_ledger_closed_is_projected_onto_snapshot_and_survives_republish(tmp_path):
    from twinbox_core import case_ledger

    scope_id = "acct-a"
    key = "thread-key-1"
    ref = case_ref(scope_id, key)
    case_ledger.append_record(
        tmp_path, case_ref=ref, attribute="lifecycle_state", value="closed",
        valid_from="2026-09-01T00:00:00+00:00", source="analysis_derived",
    )
    result = _publish(tmp_path, cases=[{"case_key": key, "mail_refs": ["m1"]}], classifications=[])
    row = result["active_snapshot"]["cases"][0]
    assert row["case_ref"] == ref
    assert row["lifecycle"]["state"] == "closed"

    # Re-publishing (atomic replace) still projects the ledger's closed state;
    # the projection never rewrites or deletes a ledger line.
    result2 = _publish(
        tmp_path, cases=[{"case_key": key, "mail_refs": ["m1"]}], classifications=[],
        source_revision=2,
    )
    assert result2["active_snapshot"]["cases"][0]["lifecycle"]["state"] == "closed"
    assert len(case_ledger.load_records(tmp_path)) == 1
