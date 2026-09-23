"""Synthetic classification regressions; never call an embedding provider."""
from unittest.mock import Mock

from twinbox_core import events, rules


def test_approval_semantics_do_not_match_first_weekly_type(tmp_path, monkeypatch):
    pack = {
        "id": "synthetic",
        "attention_hints": [{"utterances": ["approval requested"]}],
        "classification": {"event_types": [
            {"id": "weekly", "when": {"semantic": {"utterances": ["weekly report"]}}},
            {"id": "approval", "when": {"semantic": {"utterances": ["approval requested"]}}},
        ]},
    }
    monkeypatch.setattr(events, "load_active_pack", lambda _: pack)
    monkeypatch.setattr(rules, "load_vector", lambda *_: [1.0, 0.0])
    embed = Mock(side_effect=lambda texts: [[1.0, 0.0] if t == "approval requested" else [0.0, 1.0] for t in texts])
    monkeypatch.setattr(rules, "embed_texts", embed)
    result = events.extract_events({"envelopes": [{"id": "1", "folder": "INBOX", "subject": "Please approve"}]}, tmp_path)
    assert result[0]["type"] == "approval"
    assert embed.call_args_list[0].args[0] == ["weekly report"]
    assert embed.call_args_list[1].args[0] == ["approval requested"]


def test_pack_attention_is_not_a_type_rule(tmp_path, monkeypatch):
    pack = {"id": "synthetic", "attention_hints": [{"utterances": ["approval"]}],
            "classification": {"event_types": [{"id": "weekly", "when": {}}]}}
    monkeypatch.setattr(events, "load_active_pack", lambda _: pack)
    monkeypatch.setattr(rules, "load_vector", lambda *_: [1.0, 0.0])
    embed = Mock(return_value=[[1.0, 0.0]])
    monkeypatch.setattr(rules, "embed_texts", embed)
    result = events.extract_events({"envelopes": [{"id": "1", "subject": "approval"}]}, tmp_path)
    assert result[0]["type"] == "unclassified"
    embed.assert_not_called()


def test_hard_rules_and_no_pack_remain_compatible(tmp_path, monkeypatch):
    monkeypatch.setattr(events, "load_active_pack", lambda _: {"classification": {"event_types": [
        {"id": "approval", "when": {"hard": {"subject_regex": "approve"}}}
    ]}})
    result = events.extract_events({"envelopes": [{"id": "1", "subject": "Please approve"}]}, tmp_path)
    assert result[0]["type"] == "approval"
    monkeypatch.setattr(events, "load_active_pack", lambda _: None)
    assert events.extract_events({"envelopes": [{"id": "1"}]}, tmp_path)[0]["type"] == "unclassified"


def test_legacy_attention_band_signature(tmp_path, monkeypatch):
    monkeypatch.setattr(rules, "load_vector", lambda *_: [1.0, 0.0])
    monkeypatch.setattr(rules, "embed_texts", lambda _: [[1.0, 0.0]])
    assert rules.semantic_band({"attention_hints": [{"utterances": ["approval"]}]}, {"id": "1"}, tmp_path) == "hit"
    assert rules.semantic_band(None, {"id": "1"}, tmp_path) == "skip"


import json
from pathlib import Path
import pytest
from twinbox_core.pack import PackError, load_pack_file, validate_pack
from twinbox_core.project import project_item


def _classify(tmp_path, monkeypatch, types):
    pack = validate_pack({"id": "synthetic", "classification": {"event_types": types}})
    monkeypatch.setattr(events, "load_active_pack", lambda _: pack)
    return events.extract_events({"envelopes": [{"id": "1", "subject": "review request"}]}, tmp_path)[0]


def test_priority_is_explicit_not_order(tmp_path, monkeypatch):
    types = [
        {"id": "routine", "priority": 1, "when": {"subject_regex": "review"}},
        {"id": "decision", "priority": 10, "label": "Decision", "when": {"subject_regex": "review"},
         "tags": {"department": ["synthetic-team"]}, "axes": {"urgency": "high"}},
    ]
    result = _classify(tmp_path, monkeypatch, types)
    assert result["type"] == "decision"
    assert result["semantics"]["tags"] == {"department": ["synthetic-team"]}
    assert result["semantics"]["evidence_basis"] == "explicit"
    reversed_result = _classify(tmp_path, monkeypatch, list(reversed(types)))["semantics"]
    # Source fingerprints identify the exact pack document, including list order.
    assert {k: v for k, v in reversed_result.items() if k != "pack"} == {k: v for k, v in result["semantics"].items() if k != "pack"}


def test_equal_priority_conflict_does_not_pick_first(tmp_path, monkeypatch):
    types = [{"id": name, "when": {"subject_regex": "review"}} for name in ("weekly", "approval")]
    result = _classify(tmp_path, monkeypatch, types)
    assert result["type"] == "unclassified"
    assert result["semantics"]["primary_event_type"] is None
    assert result["classification_status"] == "needs_confirmation"
    assert [r["id"] for r in result["classification_candidates"]] == ["approval", "weekly"]
    assert _classify(tmp_path, monkeypatch, types[::-1])["classification_candidates"] == result["classification_candidates"]


@pytest.mark.parametrize("bad", [
    {"event_types": "approval"},
    {"event_types": [{"id": "a"}, {"id": "a"}]},
    {"event_types": [{"id": "a", "priority": True}]},
    {"event_types": [{"id": "a", "when": {"subject_regex": "["}}]},
    {"event_types": [{"id": "a", "when": {"unknown_operator": "review"}}]},
    {"event_types": [{"id": "a", "when": {"semantic": {"utterances": ["review"], "threshold_low": .9, "threshold_high": .5}}}]},
    {"event_types": [{"id": "a", "tags": {"acl": ["admin"]}}]},
    {"event_types": [{"id": "a", "axes": {"urgency": {"body": "not an axis"}}}]},
    {"defaults": {"broadcast": "delete"}},
])
def test_invalid_pack_rejected_without_mutating_input(bad):
    raw = {"id": "invalid", "classification": bad}
    before = json.dumps(raw)
    with pytest.raises(PackError):
        validate_pack(raw)
    assert json.dumps(raw) == before


def test_three_department_examples_same_engine(tmp_path, monkeypatch):
    fixtures = Path(__file__).parent / "fixtures" / "semantic_policy"
    for path in sorted(fixtures.glob("*.yaml")):
        pack = load_pack_file(path)
        monkeypatch.setattr(events, "load_active_pack", lambda _, p=pack: p)
        event = events.extract_events({"envelopes": [{"id": "1", "subject": "review request"}]}, tmp_path)[0]
        assert event["semantics"]["tags"]["department"] == [pack["id"]]
        assert event["semantics"]["pack"]["fingerprint"] == pack["fingerprint"]
    assert len(list(fixtures.glob("*.yaml"))) == 3


def test_inferred_urgency_and_recipient_role_do_not_authorize_action():
    assert project_item({"queue_tags": [], "axes": {"urgency": "high"}, "recipient_role": "to"}, None) != "action_required"


def test_declared_axes_are_projected_without_changing_responsibility():
    from twinbox_core.project import _axes
    item = {"recipient_role": "cc", "semantics": {"axes": {"customer_impact": "high", "sensitivity": "restricted"}}}
    assert _axes(item)["customer_impact"] == "high"
    assert _axes(item)["sensitivity"] == "restricted"
    assert project_item(item, None) == "reference"


def test_catalog_comes_from_pack_ids_not_client_enum():
    from twinbox_core.pack import classification_catalog
    pack = validate_pack({"id": "synthetic", "classification": {"event_types": [
        {"id": "new.business.kind", "label": "New business kind", "tags": {"project": ["P1", "P2"]}}
    ]}})
    catalog = classification_catalog(pack)
    assert catalog["event_types"] == [{"id": "new.business.kind", "label": "New business kind", "priority": 0}]
    assert catalog["tags"] == {"project": ["P1", "P2"]}

@pytest.mark.parametrize("output_policy", [
    {"excerpt": {"default": {"mode": "allow"}}},
    {"excerpt": {"default": {"mode": "reference_only", "max_chars": 8}}},
    {"excerpt": {"default": {"mode": "reference_only"}, "axes": {"sharing": {"short": {"mode": "truncate_excerpt"}}}}},
    {"excerpt": {"default": {"mode": "reference_only"}, "axes": {"security": {"open": {"mode": "allow"}}}}},
])
def test_output_policy_is_declared_and_fails_closed_when_invalid(output_policy):
    with pytest.raises(PackError):
        validate_pack({"id": "synthetic", "classification": {"event_types": []}, "output_policy": output_policy})
