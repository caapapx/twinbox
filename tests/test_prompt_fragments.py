from __future__ import annotations

import pytest

from twinbox_core.prompt_fragments import (
    base_human_context_rules,
    calibration_rules,
    confidence_calibration_note,
    material_rules,
    persona_fewshot,
    urgent_fewshot,
)


def test_base_human_context_rules_content() -> None:
    text = base_human_context_rules()
    assert "onboarding_profile_notes" in text
    assert "mail_evidence" in text
    assert "user_confirmed_fact" in text
    assert "calibration_notes" not in text
    assert "material_extracts" not in text
    assert "evidence array" not in text.lower()


def test_calibration_and_material_fragments() -> None:
    assert "calibration_notes" in calibration_rules()
    assert "material_extracts" in material_rules()
    assert "template_hint" in material_rules()


def test_confidence_calibration_note_phase_scope() -> None:
    c = confidence_calibration_note()
    assert "0.85" in c
    assert "urgency_score" not in c


def test_fewshot_gated_off_by_default() -> None:
    assert persona_fewshot() == ""
    assert urgent_fewshot() == ""


def test_fewshot_gated_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWINBOX_FEWSHOT", "1")
    p = persona_fewshot()
    u = urgent_fewshot()
    assert len(p) > 0 and "evidence" in p
    assert len(u) > 0 and "urgency_score" in u
    assert "cc_only" not in u
    assert "group_only" not in u
