"""Composable prompt rule fragments for Phase 2–4 LLM calls."""

from __future__ import annotations

import os


def base_human_context_rules() -> str:
    return """Human context (when present in the input JSON):
- Human-provided facts OVERRIDE email-only inference when they conflict.
- Mark evidence source: mail_evidence / user_declared_rule / user_confirmed_fact.
- If human context contradicts email-derived conclusions, flag the conflict explicitly in your reasoning output (without inventing fields absent from the schema).
- manual_habits inject periodic tasks into relevant hypotheses or outputs.
- If onboarding_profile_notes is non-null in human_context, treat it as user-declared role, habits, or preferences; cite user_confirmed_fact / onboarding_notes where appropriate."""


def calibration_rules() -> str:
    return """calibration_notes (when present in human_context) are hard relevance constraints for what the owner cares about this week; treat them as binding for prioritization, not background color."""


def material_rules() -> str:
    return """material_extracts_notes (when present): check each material's intent tag (reference vs template_hint).
- intent=reference: use as reference data for ranking or judgment; if marked synthetic, do not treat as mailbox-derived factual evidence.
- intent=template_hint: use structure as a format guide only; do not invent thread content from templates.
Do not invent threads; materials guide structure and priority, not substantive thread content."""


def confidence_calibration_note() -> str:
    return """Confidence must reflect actual certainty. Do NOT default to 0.85+. A hypothesis with limited evidence should be 0.3–0.5."""


def persona_fewshot() -> str:
    if not os.environ.get("TWINBOX_FEWSHOT"):
        return ""
    return """
## Examples (hypothesis quality)

Good: hypothesis cites concrete thread_keys and counts, e.g. evidence includes "release(6) from thread_keys in top_domains sample" tying claims to input rows.

Bad: hypothesis says "busy with many projects" with no thread_key, sender, or numeric anchor from the mailbox data — reject this pattern; ground every claim in cited input evidence.
"""


def urgent_fewshot() -> str:
    if not os.environ.get("TWINBOX_FEWSHOT"):
        return ""
    return """
## Example (urgency_score only; recipient handling is post-processed in code)

Thread A: waiting_on_me with an explicit deadline in the excerpt and no reply from the owner for several days → urgency_score around 85.
Thread B: informational FYI, no request for action, stable thread → urgency_score around 45.
Calibrate from action signals in the thread data only; do not adjust scores for cc vs To — that is applied after the model returns JSON.
"""
