"""Synthetic fixture contract for the legacy 001 adapter event examples.

The fixture intentionally uses only generic subject/header-like envelope fields.  It
is a deterministic engine contract, not an owner-signed quality or ROI corpus.
"""
from __future__ import annotations

import json
from pathlib import Path

from twinbox_core import events
from twinbox_core.pack import validate_pack


FIXTURE = Path(__file__).parent / "fixtures" / "adapter_events" / "v1.json"


def test_synthetic_adapter_event_examples_are_pack_configurable_and_body_free(tmp_path, monkeypatch):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["schema_version"] == "twinbox.adapter-event-fixture/v1"
    assert fixture["synthetic_only"] is True
    assert len(fixture["cases"]) == 3

    pack = validate_pack(fixture["pack"])
    monkeypatch.setattr(events, "load_active_pack", lambda _: pack)
    envelopes = [case["envelope"] for case in fixture["cases"]]
    extracted = events.extract_events({"source_account": "fixture", "envelopes": envelopes}, tmp_path)

    assert [event["type"] for event in extracted] == [
        case["expected"]["event_type"] for case in fixture["cases"]
    ]
    for event, case in zip(extracted, fixture["cases"], strict=True):
        assert event["classification_status"] == "classified"
        assert event["semantics"]["tags"] == case["expected"]["tags"]
        assert event["semantics"]["axes"] == case["expected"]["axes"]
        assert event["semantics"]["evidence_basis"] == "explicit"
        assert event["mail_ref"] == {
            "folder": case["envelope"]["folder"],
            "uid": case["envelope"]["id"],
            "message_id": case["envelope"]["message_id"],
        }
        assert set(event["fields"]) == {"subject", "from_addr", "recipient_role"}
        assert "body" not in json.dumps(event, ensure_ascii=False).lower()
