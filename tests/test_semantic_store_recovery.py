import json

import pytest

from twinbox_core.classification_store import (
    classification_path,
    load_classifications,
    publish_classifications,
    recover_classifications,
)
from twinbox_core.evidence_contract import SourceGrant
from twinbox_core.feedback import feedback_audit_path, feedback_path, process_feedback


def _seed(root):
    published = publish_classifications(
        root,
        scope_id="scope-a",
        pack_fingerprint="pack-a",
        classifier_version="classifier-a",
        source_revision=1,
        source_digest="source-a",
        coverage={"window": {"since": "2026-09-01", "until": "2026-09-20"}},
        cases=[{"case_key": "case-a", "mail_refs": ["mail-1"], "evidence_refs": ["mail-1:excerpt-1"]}],
        classifications=[{"case_key": "case-a", "status": "classified", "primary_event_type": "review"}],
        observed_at="2026-09-20T00:00:00Z",
    )
    return published, published["active_snapshot"]["cases"][0]["case_ref"]


def _grant():
    return SourceGrant(
        scope_id="scope-a",
        account_ref="account-a",
        mail_refs=frozenset({"mail-1"}),
        evidence_refs=frozenset({"mail-1:excerpt-1"}),
        enabled=True,
    )


def _confirmation(case_ref):
    return {
        "schema_version": "1.0",
        "decision_id": "decision-recovery",
        "scope_id": "scope-a",
        "case_ref": case_ref,
        "expected_revision": 1,
        "actor_ref": "reviewer-a",
        "kind": "human_confirmation",
        "evidence_refs": ["mail-1:excerpt-1"],
        "decision": {"confirmation": "responsibility_confirmed", "reason": "confirmed"},
    }


def _apply(root, payload):
    return process_feedback(
        root,
        payload,
        grant=_grant(),
        actor_ref="reviewer-a",
        allowed_kinds={"human_confirmation"},
    )


def test_corrupt_active_snapshot_can_be_explicitly_restored_from_last_valid_backup(tmp_path):
    first, _ = _seed(tmp_path)
    publish_classifications(
        tmp_path,
        scope_id="scope-a",
        pack_fingerprint="pack-a",
        classifier_version="classifier-a",
        source_revision=2,
        source_digest="source-b",
        coverage={"window": {"since": "2026-09-01", "until": "2026-09-20"}},
        cases=[], classifications=[], expected_revision=first["revision"],
        observed_at="2026-09-20T01:00:00Z",
    )
    classification_path(tmp_path).write_text("{broken", encoding="utf-8")

    restored = recover_classifications(tmp_path, "scope-a")

    assert restored["revision"] == first["revision"]
    assert load_classifications(tmp_path, "scope-a") == restored


def test_feedback_retry_recovers_after_classification_write_but_before_feedback_store(tmp_path, monkeypatch):
    import twinbox_core.feedback as feedback

    _, case_ref = _seed(tmp_path)
    payload = _confirmation(case_ref)
    original = feedback._atomic_write
    failed = False

    def fail_feedback_once(path, value):
        nonlocal failed
        if path == feedback_path(tmp_path) and not failed:
            failed = True
            raise OSError("simulated feedback-store crash")
        return original(path, value)

    monkeypatch.setattr(feedback, "_atomic_write", fail_feedback_once)
    with pytest.raises(OSError, match="simulated"):
        _apply(tmp_path, payload)
    monkeypatch.setattr(feedback, "_atomic_write", original)

    result = _apply(tmp_path, payload)

    assert result["status"] == "accepted"
    assert result["classification_revision"] == 2
    stored = json.loads(feedback_path(tmp_path).read_text(encoding="utf-8"))
    assert [row["decision_id"] for row in stored["decisions"]] == ["decision-recovery"]
    assert len(feedback_audit_path(tmp_path).read_text(encoding="utf-8").splitlines()) == 1


def test_idempotent_retry_repairs_missing_audit_line(tmp_path, monkeypatch):
    import twinbox_core.feedback as feedback

    _, case_ref = _seed(tmp_path)
    payload = _confirmation(case_ref)
    original = feedback._append_audit
    failed = False

    def fail_audit_once(root, record):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("simulated audit crash")
        return original(root, record)

    monkeypatch.setattr(feedback, "_append_audit", fail_audit_once)
    with pytest.raises(OSError, match="simulated"):
        _apply(tmp_path, payload)
    monkeypatch.setattr(feedback, "_append_audit", original)

    result = _apply(tmp_path, payload)
    assert result["status"] == "accepted"
    lines = feedback_audit_path(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["decision_id"] == "decision-recovery"
