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
8. waiting_on_me MUST be decided from the LATEST message in the thread (is_latest=true). If the latest message is an approval/同意/已处理 reply, do NOT list it as pending; set resolved_by_reply instead.
9. why must quote evidence from the provided body; do not speculate.
10. Output ONLY the JSON object. No markdown, no explanation.
Additional optional field on pending_replies: "resolved_by_reply": true when the latest mail clears the wait.
"""


def _body_for(env: dict[str, Any], body_map: dict[str, Any], *, latest: bool) -> str:
    mid = str(env.get("id", ""))
    folder = str(env.get("folder", "INBOX") or "INBOX")
    entry = body_map.get(f"{folder}#{mid}") or body_map.get(mid, {})
    body = ""
    if isinstance(entry, dict):
        body = str(entry.get("body", "") or "")
    elif isinstance(entry, str):
        body = entry
    if not body:
        body = str(env.get("body", "") or "")
    limit = 2000 if latest else 800
    return body[:limit]


def _build_prompt(context: dict[str, Any], human_context: dict[str, Any] | None = None) -> str:
    """Build the user prompt from Phase 1 context + optional human context."""
    from .pulse import normalize_thread_key

    envelopes = [e for e in context.get("envelopes", []) if isinstance(e, dict)]
    body_map = context.get("sampled_bodies", {})
    grouped: dict[str, list[dict[str, Any]]] = {}
    for env in envelopes:
        grouped.setdefault(normalize_thread_key(env.get("subject")), []).append(env)

    lines = [f"## Mailbox data (lookback={context.get('lookback_days', 7)} days, "
             f"owner_domain={context.get('owner_domain', 'unknown')}):\n"]

    idx = 0
    for tk, rows in grouped.items():
        rows_sorted = sorted(rows, key=lambda r: str(r.get("date", "")), reverse=True)
        lines.append(f"### thread_key={tk} messages={len(rows_sorted)}")
        for i, env in enumerate(rows_sorted):
            latest = i == 0
            body_preview = _body_for(env, body_map, latest=latest)
            flags_str = ", ".join(env.get("flags", []))
            lines.append(
                f"[{idx}] thread_key={tk} is_latest={str(latest).lower()} "
                f"recipient_role={env.get('recipient_role', 'unknown')} "
                f"subject={env.get('subject', '')} | "
                f"from={env.get('from_name', '')} <{env.get('from_addr', '')}> | "
                f"to={env.get('to', '')} | cc={env.get('cc', '')} | "
                f"date={env.get('date', '')} | folder={env.get('folder', 'INBOX')} | "
                f"flags=[{flags_str}]"
            )
            if body_preview:
                lines.append(f"  body_preview: {body_preview}")
            idx += 1

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
    try:
        from .select import choose_candidates
        from .rules import skip_llm_envelopes
        from .pack import load_active_pack
        from .events import extract_events
        pack = load_active_pack(state_root)
        candidates, select_diag = choose_candidates(context, state_root)
        skipped = skip_llm_envelopes(pack, context.get("envelopes", []))
        skip_ids = {(str(e.get("folder")), str(e.get("id"))) for e in skipped}
        if candidates:
            context = dict(context)
            context["envelopes"] = [
                e for e in candidates
                if (str(e.get("folder")), str(e.get("id"))) not in skip_ids
            ]
        extract_events(context, state_root)
        context.setdefault("stats", {})
        if isinstance(context["stats"], dict):
            context["stats"].update(select_diag)
    except Exception:
        pass
    prompt = _build_prompt(context, human_context)

    raw = ""
    try:
        raw = call_llm(prompt, max_tokens=4096, system_prompt=SYSTEM_PROMPT)
        cleaned = clean_json_text(raw)
        result = json.loads(cleaned)
    except (LLMError, json.JSONDecodeError) as exc:
        err_dir = state_root / "runtime" / "validation" / "phase-4"
        err_dir.mkdir(parents=True, exist_ok=True)
        (err_dir / "last-analysis-error.json").write_text(
            json.dumps({
                "error": str(exc),
                "raw_preview": str(raw)[:800],
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {"ok": False, "error": f"LLM analysis failed: {exc}"}

    if not isinstance(result, dict):
        return {"ok": False, "error": "LLM returned non-object"}

    # Write Phase 4 outputs
    phase4_dir = state_root / "runtime" / "validation" / "phase-4"
    phase4_dir.mkdir(parents=True, exist_ok=True)

    from .imap_fetch import _write_json, _now_iso
    from .pulse import normalize_thread_key

    def _norm_rows(rows: object) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not isinstance(rows, list):
            return out
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            item["thread_key"] = normalize_thread_key(item.get("thread_key", ""))
            out.append(item)
        return out

    urgent = _norm_rows(result.get("daily_urgent", []))
    pending = [
        p for p in _norm_rows(result.get("pending_replies", []))
        if not p.get("resolved_by_reply")
    ]
    sla = _norm_rows(result.get("sla_risks", []))
    import yaml
    urgent_out = {"generated_at": _now_iso(), "daily_urgent": urgent}
    (phase4_dir / "daily-urgent.yaml").write_text(
        yaml.safe_dump(urgent_out, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    pending_out = {"generated_at": _now_iso(), "pending_replies": pending}
    (phase4_dir / "pending-replies.yaml").write_text(
        yaml.safe_dump(pending_out, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
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
