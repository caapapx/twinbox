"""Single-pass LLM analysis — combines intent + urgency + pending + weekly.

Replaces the original 4-phase pipeline with one LLM call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .llm import LLMError, call_llm, clean_json_text

SYSTEM_PROMPT = """You are an enterprise email assistant producing daily actionable outputs for a mailbox owner.

## Your task

Analyze the thread data below and produce a JSON object with this structure:
{
  "daily_urgent": [
    {
      "thread_key": "<thread key>",
      "urgency_score": <0-100>,
      "reason_code": "<due_soon | waiting_on_me | sla_risk | carry_over | monitor_only>",
      "why": "<one sentence in Chinese explaining urgency>",
      "action_hint": "<concrete next action in Chinese>",
      "waiting_on": "<who/what is being waited on>",
      "evidence_source": "mail_evidence"
    }
  ],
  "pending_replies": [
    {
      "thread_key": "<thread key>",
      "waiting_on_me": true,
      "reason_code": "<waiting_on_me | approval_needed | missing_confirmation>",
      "why": "<why I need to reply, in Chinese>",
      "suggested_action": "<what to do, in Chinese>",
      "evidence_source": "mail_evidence"
    }
  ],
  "sla_risks": [
    {
      "thread_key": "<thread key>",
      "risk_type": "<stalled | overdue | no_response>",
      "risk_description": "<in Chinese>",
      "days_since_last_activity": <number>,
      "suggested_action": "<in Chinese>"
    }
  ],
  "weekly_brief": {
    "period": "<date range>",
    "total_threads_in_window": <number>,
    "action_now": [
      {"thread_key":"<key>", "why":"<Chinese>", "action":"<Chinese>"}
    ],
    "important_changes": [
      {"thread_key":"<key>", "change":"<Chinese>", "impact":"<Chinese>"}
    ],
    "top_actions": ["<top 3 actions for this week, in Chinese>"],
    "rhythm_observation": "<one paragraph in Chinese about work rhythm>"
  }
}

## Rules
1. daily_urgent: rank by urgency_score desc. Include threads where action is needed TODAY.
2. pending_replies: only threads where the mailbox owner needs to respond or approve.
3. sla_risks: threads that are stalled or overdue.
4. weekly_brief: summarize the lookback window, not just today.
5. Human context (profile_notes, calibration_notes) OVERRIDE email-only inference when they conflict.
6. calibration_notes are hard relevance constraints for what the owner cares about this week.
7. Do NOT invent threads not in the input. Every thread_key must come from the data.
8. Output ONLY the JSON object. No markdown, no explanation."""


def _build_prompt(context: dict[str, Any], human_context: dict[str, Any] | None = None) -> str:
    """Build the user prompt from Phase 1 context + optional human context."""
    envelopes = context.get("envelopes", [])
    body_map = context.get("sampled_bodies", {})

    lines = [f"## Mailbox data (lookback={context.get('lookback_days', 7)} days, "
             f"owner_domain={context.get('owner_domain', 'unknown')}):\n"]

    for i, env in enumerate(envelopes[:100]):  # cap at 100 threads
        mid = str(env.get("id", ""))
        body_entry = body_map.get(mid, {})
        body_preview = str(body_entry.get("body", ""))[:300] if isinstance(body_entry, dict) else ""
        flags_str = ", ".join(env.get("flags", []))
        lines.append(
            f"[{i}] subject={env.get('subject', '')} | "
            f"from={env.get('from_name', '')} <{env.get('from_addr', '')}> | "
            f"date={env.get('date', '')} | folder={env.get('folder', 'INBOX')} | "
            f"flags=[{flags_str}]"
        )
        if body_preview:
            lines.append(f"  body_preview: {body_preview}")

    if human_context:
        lines.append("\n## Human context:")
        if human_context.get("profile_notes"):
            lines.append(f"profile_notes: {human_context['profile_notes']}")
        if human_context.get("calibration_notes"):
            lines.append(f"calibration_notes: {human_context['calibration_notes']}")

    return "\n".join(lines)


def _load_human_context(state_root: Path) -> dict[str, Any] | None:
    path = state_root / "runtime" / "context" / "human-context.yaml"
    if not path.is_file():
        return None
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def run_analysis(state_root: Path) -> dict[str, Any]:
    """Run single-pass LLM analysis on the fetched mail context."""
    context_path = state_root / "runtime" / "context" / "phase1-context.json"
    if not context_path.is_file():
        return {"ok": False, "error": "No mail context. Run sync first."}

    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "error": f"Failed to read context: {exc}"}

    if not isinstance(context, dict) or not context.get("envelopes"):
        return {"ok": False, "error": "Empty mail context. Run sync first."}

    human_context = _load_human_context(state_root)
    prompt = _build_prompt(context, human_context)

    try:
        raw = call_llm(prompt, max_tokens=4096, system_prompt=SYSTEM_PROMPT)
        cleaned = clean_json_text(raw)
        result = json.loads(cleaned)
    except (LLMError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"LLM analysis failed: {exc}"}

    if not isinstance(result, dict):
        return {"ok": False, "error": "LLM returned non-object"}

    # Write Phase 4 outputs
    phase4_dir = state_root / "runtime" / "validation" / "phase-4"
    phase4_dir.mkdir(parents=True, exist_ok=True)

    from .imap_fetch import _write_json, _now_iso

    # daily-urgent.yaml
    urgent = result.get("daily_urgent", [])
    if isinstance(urgent, list):
        import yaml
        urgent_out = {"generated_at": _now_iso(), "daily_urgent": urgent}
        (phase4_dir / "daily-urgent.yaml").write_text(
            yaml.safe_dump(urgent_out, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    # pending-replies.yaml
    pending = result.get("pending_replies", [])
    if isinstance(pending, list):
        import yaml
        pending_out = {"generated_at": _now_iso(), "pending_replies": pending}
        (phase4_dir / "pending-replies.yaml").write_text(
            yaml.safe_dump(pending_out, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    # sla-risks.yaml
    sla = result.get("sla_risks", [])
    if isinstance(sla, list):
        import yaml
        sla_out = {"generated_at": _now_iso(), "sla_risks": sla}
        (phase4_dir / "sla-risks.yaml").write_text(
            yaml.safe_dump(sla_out, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    # weekly-brief-raw.json
    weekly = result.get("weekly_brief", {})
    if isinstance(weekly, dict):
        weekly["generated_at"] = _now_iso()
        _write_json(phase4_dir / "weekly-brief-raw.json", weekly)

    return {
        "ok": True,
        "urgent_count": len(urgent) if isinstance(urgent, list) else 0,
        "pending_count": len(pending) if isinstance(pending, list) else 0,
        "sla_count": len(sla) if isinstance(sla, list) else 0,
    }
