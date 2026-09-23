"""Client projections use the pack catalog and keep evidence lazy."""
from __future__ import annotations

from twinbox_core.classification_store import publish_classifications


def _seed(root):
    (root / "packs").mkdir(parents=True)
    (root / "packs/user.yaml").write_text(
        """id: test-pack\nversion: 1.0.0\nclassification:\n  event_types:\n    - id: review.dynamic\n      label: Dynamic review\n      tags: {project: [alpha]}\n      axes: {urgency: medium}\n      when: {hard: {subject_regex: review}}\n""",
        encoding="utf-8",
    )
    return publish_classifications(
        root,
        scope_id="scope-a",
        cases=[{"case_key": "known", "mail_refs": ["m1"], "evidence_refs": ["m1:e1"]},
               {"case_key": "future", "mail_refs": ["m2"], "evidence_refs": ["m2:e1"]}],
        classifications=[
            {"case_key": "known", "status": "classified", "primary_event_type": "review.dynamic", "tags": {"project": ["alpha"]}},
            {"case_key": "future", "status": "classified", "primary_event_type": "future.type", "tags": {"future": ["raw"]}},
        ],
        coverage={"state": "complete"}, pack_fingerprint="p1", classifier_version="c1", source_revision=1,
    )


def test_dynamic_catalog_and_unknown_raw_label(tmp_path):
    from twinbox_core.semantic_client import project_semantics

    _seed(tmp_path)
    catalog = project_semantics(tmp_path, scope_id="scope-a", action="catalog")
    assert catalog["catalog"]["event_types"][0]["id"] == "review.dynamic"

    rows = project_semantics(tmp_path, scope_id="scope-a", action="list")["cases"]
    by_type = {row["primary_event_type"]: row for row in rows}
    assert by_type["review.dynamic"]["display"]["event_type"] == "Dynamic review"
    assert by_type["future.type"]["display"]["event_type"] == "future.type"


def test_legacy_fields_stay_and_evidence_is_on_demand(tmp_path):
    from twinbox_core.semantic_client import project_semantics

    stored = _seed(tmp_path)
    ref = stored["active_snapshot"]["cases"][0]["case_ref"]
    compact = project_semantics(tmp_path, scope_id="scope-a", action="get", case_ref=ref)
    assert compact["case"]["primary_event_type"] == "review.dynamic"
    assert compact["case"]["tags"] == {"project": ["alpha"]}
    assert "evidence_refs" not in compact["case"]

    expanded = project_semantics(tmp_path, scope_id="scope-a", action="get", case_ref=ref, include_evidence=True)
    assert expanded["case"]["evidence_refs"] == ["m1:e1"]
    assert "mail_refs" not in expanded["case"]


def test_cli_semantics_wraps_versioned_projection(tmp_path, monkeypatch):
    from twinbox_core import cli

    _seed(tmp_path)
    monkeypatch.setattr(cli, "_account_root", lambda account_id=None: tmp_path)
    monkeypatch.setattr(cli, "_resolved_account_id", lambda account_id=None: "scope-a")
    result = cli.cmd_semantics(["catalog"], account_id="scope-a")
    assert result["ok"] is True
    assert result["data"]["schema_version"] == "1.0"
    assert result["data"]["catalog"]["event_types"][0]["id"] == "review.dynamic"
