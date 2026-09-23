"""Single-pass LLM analysis — combines intent + urgency + pending + weekly.

Replaces the original 4-phase pipeline with one LLM call.
"""

from __future__ import annotations

import json
import os
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
11. Each message has evidence_id. why/action fields MUST set evidence_refs to those ids from this prompt. Never invent ids or thread_keys.
12. waiting_on_me=true only with explicit evidence the mailbox owner must reply or approve. To/Cc membership alone is not enough. action_target is the named actor in the body when it is not the owner.
13. Counts, dates, and day-aging quoted from mail are reported values; keep evidence_refs and do not recompute them as live project facts.
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


PROMPT_DEFAULT_MAX_CHARS = 1_000_000
PROMPT_MIN_MAX_CHARS = 512
PROMPT_HARD_MAX_CHARS = 4_000_000
PROMPT_CHARS_PER_ESTIMATED_TOKEN = 4


def _prompt_max_chars() -> int:
    """Return the hard character budget for one analysis prompt.

    The default is intentionally below a typical million-token model window:
    email bodies are untrusted input and Twinbox must bound the amount sent to
    the model even when a mailbox contains hundreds of messages.  The
    environment override is useful for controlled local benchmarks, but is
    still clamped so a typo cannot remove the safety bound.
    """
    raw = os.environ.get("TWINBOX_ANALYSIS_PROMPT_MAX_CHARS", "")
    try:
        value = int(raw) if raw.strip() else PROMPT_DEFAULT_MAX_CHARS
    except (TypeError, ValueError):
        value = PROMPT_DEFAULT_MAX_CHARS
    return max(PROMPT_MIN_MAX_CHARS, min(value, PROMPT_HARD_MAX_CHARS))


def _message_header(
    tk: str,
    env: dict[str, Any],
    *,
    latest: bool,
    body_available: bool | None = None,
) -> str:
    flags = env.get("flags", [])
    if isinstance(flags, (list, tuple, set)):
        flags_str = ", ".join(str(flag) for flag in flags)
    else:
        flags_str = str(flags or "")
    evid = _evidence_id(env)
    return (
        f"evidence_id={evid} thread_key={tk} is_latest={str(latest).lower()} "
        f"recipient_role={env.get('recipient_role', 'unknown')} "
        f"body_available={str(bool(body_available if body_available is not None else env.get('body'))).lower()} "
        f"subject={env.get('subject', '')} | "
        f"from={env.get('from_name', '')} <{env.get('from_addr', '')}> | "
        f"to={env.get('to', '')} | cc={env.get('cc', '')} | "
        f"date={env.get('date', '')} | folder={env.get('folder', 'INBOX')} | "
        f"flags=[{flags_str}]"
    )


def _compact_message_header(tk: str, env: dict[str, Any], *, latest: bool) -> str:
    """Small fallback header that still gives the model a valid evidence ref."""
    return (
        f"evidence_id={_evidence_id(env)} thread_key={tk} "
        f"is_latest={str(latest).lower()} subject={str(env.get('subject', ''))[:160]}"
    )


def _append_with_budget(parts: list[str], text: str, remaining: int) -> tuple[int, bool]:
    if remaining <= 0 or not text:
        return remaining, bool(text)
    if len(text) <= remaining:
        parts.append(text)
        return remaining - len(text), False
    if remaining > 0:
        parts.append(text[:remaining])
    return 0, True


def _prompt_stats(context: dict[str, Any], prompt: str) -> dict[str, Any]:
    stats = context.setdefault("stats", {})
    if not isinstance(stats, dict):
        stats = {}
        context["stats"] = stats
    value = {
        "prompt_chars": len(prompt),
        "prompt_estimated_tokens": (len(prompt) + PROMPT_CHARS_PER_ESTIMATED_TOKEN - 1)
        // PROMPT_CHARS_PER_ESTIMATED_TOKEN,
        "prompt_char_limit": _prompt_max_chars(),
    }
    stats.update(value)
    return value


def _build_prompt(context: dict[str, Any], human_context: dict[str, Any] | None = None) -> str:
    """Build a deterministic, bounded prompt from the selected mail context.

    Headers (including opaque evidence IDs) are retained before body previews.
    Latest-message previews are preferred, then historical previews are added
    in stable thread/date order until the hard budget is exhausted.  This
    keeps the analysis useful for a large mailbox without ever passing an
    unbounded concatenation of email text to the LLM.
    """
    from .pulse import normalize_thread_key

    limit = _prompt_max_chars()
    envelopes = [e for e in context.get("envelopes", []) if isinstance(e, dict)]
    body_map = context.get("sampled_bodies", {})
    grouped: dict[str, list[dict[str, Any]]] = {}
    for env in envelopes:
        grouped.setdefault(normalize_thread_key(env.get("subject")), []).append(env)

    prefix = (
        f"## Mailbox data (lookback={context.get('lookback_days', 7)} days, "
        f"owner_domain={context.get('owner_domain', 'unknown')}):\n"
    )
    thread_rows: list[tuple[str, list[dict[str, Any]]]] = []
    header_lines: list[str] = []
    detail_chunks: list[tuple[int, str]] = []
    total_body_messages = 0
    for tk, rows in grouped.items():
        rows_sorted = sorted(rows, key=lambda r: str(r.get("date", "")), reverse=True)
        thread_rows.append((tk, rows_sorted))
        header_lines.append(f"### thread_key={tk} messages={len(rows_sorted)}")
        for i, env in enumerate(rows_sorted):
            latest = i == 0
            body_preview = _body_for(env, body_map, latest=latest)
            header_lines.append(
                f"[{len(header_lines)}] "
                f"{_message_header(tk, env, latest=latest, body_available=bool(body_preview))}"
            )
            if body_preview:
                total_body_messages += 1
                detail_chunks.append(
                    (
                        0 if latest else 1,
                        f"body_preview evidence_id={_evidence_id(env)}: {body_preview}",
                    )
                )

    # A compact mandatory section retains every thread/message evidence ID.  In
    # normal operation it is far below the 1M-character default.  If a local
    # benchmark deliberately sets a tiny budget, fall back to compact headers
    # rather than slicing through a full metadata line.
    mandatory = "\n".join(header_lines)
    human_lines: list[str] = []
    if human_context:
        human_lines.append("\n## Human context:")
        if human_context.get("profile_notes"):
            human_lines.append(f"profile_notes: {human_context['profile_notes']}")
        if human_context.get("calibration_notes"):
            human_lines.append(f"calibration_notes: {human_context['calibration_notes']}")
    human_text = "\n".join(human_lines)

    parts: list[str] = []
    remaining = limit
    truncated = False
    remaining, cut = _append_with_budget(parts, prefix, remaining)
    truncated = truncated or cut
    remaining, cut = _append_with_budget(parts, mandatory, remaining)
    truncated = truncated or cut

    # If the full mandatory metadata did not fit, rebuild it using compact
    # per-message refs.  This is only reachable for intentionally tiny limits.
    if cut:
        compact_lines: list[str] = []
        for tk, rows_sorted in thread_rows:
            compact_lines.append(f"### thread_key={tk} messages={len(rows_sorted)}")
            for i, env in enumerate(rows_sorted):
                compact_lines.append(
                    f"[{len(compact_lines)}] "
                    f"{_compact_message_header(tk, env, latest=i == 0)}"
                )
        parts = []
        remaining = limit
        remaining, cut_prefix = _append_with_budget(parts, prefix, remaining)
        remaining, cut_compact = _append_with_budget(parts, "\n".join(compact_lines), remaining)
        truncated = True or cut_prefix or cut_compact

    # Human context outranks historical body previews.
    if human_text and remaining:
        remaining, cut = _append_with_budget(parts, human_text, remaining)
        truncated = truncated or cut

    omitted_body_messages = 0
    included_body_messages = 0
    body_section_added = False
    for _priority, chunk in sorted(enumerate(detail_chunks), key=lambda item: (item[1][0], item[0])):
        _chunk_priority, body_text = chunk
        if not remaining:
            omitted_body_messages += 1
            continue
        if not body_section_added:
            remaining, cut = _append_with_budget(parts, "\n\n## Message previews:\n", remaining)
            body_section_added = True
            truncated = truncated or cut
        before = remaining
        remaining, cut = _append_with_budget(parts, body_text + "\n", remaining)
        if before != remaining:
            included_body_messages += 1
        if cut:
            truncated = True
            omitted_body_messages += 1
            break

    prompt = "".join(parts)
    _prompt_stats(context, prompt)
    stats = context["stats"]
    stats.update({
        "prompt_truncated": bool(truncated or omitted_body_messages),
        "prompt_body_messages_available": total_body_messages,
        "prompt_body_messages_included": included_body_messages,
        "prompt_body_messages_omitted": omitted_body_messages,
        "prompt_threads": len(thread_rows),
        "prompt_messages": len(envelopes),
    })
    return prompt


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


def _envelopes_for_threads(
    context: dict[str, Any],
    candidates: list[dict[str, Any]],
    skip_ids: set[tuple[str, str]],
) -> dict[str, Any]:
    """Keep every envelope whose thread is in `candidates`, not just the latest."""
    from .pulse import normalize_thread_key

    picked = {
        normalize_thread_key(env.get("subject"))
        for env in candidates
        if isinstance(env, dict)
    }
    original = [env for env in context.get("envelopes", []) if isinstance(env, dict)]
    out = dict(context)
    out["envelopes"] = [
        env
        for env in original
        if normalize_thread_key(env.get("subject")) in picked
        and (
            str(env.get("folder", "INBOX") or "INBOX"),
            str(env.get("id", "") or ""),
        ) not in skip_ids
    ]
    return out


def _merge_stats(context: dict[str, Any], extra: dict[str, Any]) -> None:
    context.setdefault("stats", {})
    if isinstance(context["stats"], dict):
        context["stats"].update(extra)


def _select_payload(select_diag: dict[str, Any]) -> dict[str, Any]:
    out = {
        "embeddings_degraded": bool(select_diag.get("embeddings_degraded")),
        "envelope_in": select_diag.get("envelope_in"),
        "envelope_llm": select_diag.get("envelope_llm"),
        "candidate_threads": select_diag.get("candidate_threads"),
    }
    for key in (
        "prompt_chars",
        "prompt_estimated_tokens",
        "prompt_char_limit",
        "prompt_truncated",
        "prompt_body_messages_available",
        "prompt_body_messages_included",
        "prompt_body_messages_omitted",
        "prompt_threads",
        "prompt_messages",
    ):
        if key in select_diag:
            out[key] = select_diag[key]
    if select_diag.get("select_error"):
        out["select_error"] = select_diag["select_error"]
    return out


def _envelope_id(env: dict[str, Any]) -> tuple[str, str]:
    return (
        str(env.get("folder", "INBOX") or "INBOX"),
        str(env.get("id", "") or ""),
    )


def _evidence_id(env: dict[str, Any]) -> str:
    folder, uid = _envelope_id(env)
    return f"{folder}#{uid}" if uid else ""


def _issued_evidence_ids(envelopes: list[dict[str, Any]]) -> set[str]:
    return {eid for env in envelopes if (eid := _evidence_id(env))}


def _validate_label_rows(
    rows: list[dict[str, Any]],
    *,
    valid_keys: set[str],
    valid_refs: set[str],
    owner_action: bool = False,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    kept: list[dict[str, Any]] = []
    bad_keys: list[str] = []
    bad_refs: list[str] = []
    for row in rows:
        tk = str(row.get("thread_key") or "")
        if tk not in valid_keys:
            if tk:
                bad_keys.append(tk)
            continue
        refs_in = row.get("evidence_refs")
        ok_refs: list[str] = []
        if isinstance(refs_in, list):
            for ref in refs_in:
                token = str(ref or "").strip()
                if not token:
                    continue
                if token in valid_refs:
                    ok_refs.append(token)
                else:
                    bad_refs.append(token)
        row["evidence_refs"] = ok_refs
        if ok_refs:
            row["evidence_basis"] = "explicit"
        elif str(row.get("why") or "").strip():
            row["evidence_basis"] = "inferred"
        else:
            row["evidence_basis"] = "insufficient"
        if owner_action and (row.get("waiting_on_me") is True) and row["evidence_basis"] != "explicit":
            row["evidence_basis"] = "insufficient"
        if not row.get("action_target"):
            waiting = str(row.get("waiting_on") or "").strip()
            if waiting and waiting not in {"me", "我", "mailbox_owner"}:
                row["action_target"] = waiting
        kept.append(row)
    return kept, bad_keys, bad_refs


def _analyzed_id_list(envelopes: object) -> list[list[str]]:
    out: list[list[str]] = []
    seen: set[tuple[str, str]] = set()
    if not isinstance(envelopes, list):
        return out
    for env in envelopes:
        if not isinstance(env, dict):
            continue
        key = _envelope_id(env)
        if not key[1] or key in seen:
            continue
        seen.add(key)
        out.append([key[0], key[1]])
    return out


def _load_yaml_rows(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = data.get(key) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _merge_label_rows(
    old_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
    *,
    analyzed_keys: set[str],
    window_keys: set[str],
) -> list[dict[str, Any]]:
    kept = [
        row
        for row in old_rows
        if str(row.get("thread_key") or "") in window_keys
        and str(row.get("thread_key") or "") not in analyzed_keys
    ]
    return kept + new_rows


def run_analysis(
    state_root: Path,
    *,
    only_ids: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Run single-pass LLM analysis on the fetched mail context.

    ponytail: daytime patch only re-scores threads with new envelopes; nightly-full
    rewrites the window. Upgrade: incremental SLA aging without new mail.
    """
    context_path = state_root / "runtime" / "context" / "phase1-context.json"
    if not context_path.is_file():
        return {"ok": False, "error": "No mail context. Run sync first."}

    try:
        context = json.loads(context_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "error": f"Failed to read context: {exc}"}

    if not isinstance(context, dict) or not context.get("envelopes"):
        return {"ok": False, "error": "Empty mail context. Run sync first."}

    from .pulse import normalize_thread_key

    full_envelopes = [e for e in context.get("envelopes", []) if isinstance(e, dict)]
    window_keys = {normalize_thread_key(env.get("subject")) for env in full_envelopes}
    analyzed_keys: set[str] = set()
    merge_mode = bool(only_ids)
    if only_ids:
        analyzed_keys = {
            normalize_thread_key(env.get("subject"))
            for env in full_envelopes
            if _envelope_id(env) in only_ids
        }
        context = dict(context)
        context["envelopes"] = [
            env for env in full_envelopes if normalize_thread_key(env.get("subject")) in analyzed_keys
        ]
        if not context["envelopes"]:
            return {
                "ok": True,
                "skipped": True,
                "reason": "no-new-threads",
                "analyzed_ids": [],
                "select": {
                    "embeddings_degraded": False,
                    "envelope_in": len(full_envelopes),
                    "envelope_llm": 0,
                    "candidate_threads": 0,
                },
            }

    human_context = _load_human_context(state_root)
    envelope_in = len(full_envelopes)
    events_context = {**context, "envelopes": full_envelopes} if merge_mode else context
    candidates: list[dict[str, Any]] = []
    select_diag: dict[str, Any] = {"embeddings_degraded": False}
    try:
        from .select import choose_candidates
        from .rules import skip_llm_envelopes
        from .pack import load_active_pack
        pack = load_active_pack(state_root)
        candidates, select_diag = choose_candidates(context, state_root)
        skipped = skip_llm_envelopes(pack, context.get("envelopes", []))
        skip_ids = {
            (str(env.get("folder", "INBOX") or "INBOX"), str(env.get("id", "") or ""))
            for env in skipped
        }
        if candidates:
            context = _envelopes_for_threads(context, candidates, skip_ids)
            if merge_mode:
                analyzed_keys = {
                    normalize_thread_key(env.get("subject"))
                    for env in context.get("envelopes", [])
                    if isinstance(env, dict)
                }
    except Exception as exc:
        select_diag = {
            "embeddings_degraded": True,
            "select_error": type(exc).__name__,
        }
        candidates = []
    envelope_llm = len([e for e in context.get("envelopes", []) if isinstance(e, dict)])
    analyzed_ids = _analyzed_id_list(context.get("envelopes"))
    select_diag = {
        **select_diag,
        "envelope_in": envelope_in,
        "envelope_llm": envelope_llm,
        "candidate_threads": len(candidates) if candidates else envelope_in,
    }
    _merge_stats(context, select_diag)
    try:
        from .events import extract_events
        extract_events(events_context if merge_mode else context, state_root)
    except Exception as exc:
        _merge_stats(context, {"events_error": type(exc).__name__})
    prompt = _build_prompt(context, human_context)
    prompt_stats = {
        key: value
        for key, value in (context.get("stats") or {}).items()
        if str(key).startswith("prompt_")
    }
    select_diag = {**select_diag, **prompt_stats}
    prompt_diag_dir = state_root / "runtime" / "validation" / "phase-4"
    prompt_diag_dir.mkdir(parents=True, exist_ok=True)
    (prompt_diag_dir / "analysis-prompt-diagnostics.json").write_text(
        json.dumps(prompt_stats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

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
                "select": _select_payload(select_diag),
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {"ok": False, "error": f"LLM analysis failed: {exc}", "select": _select_payload(select_diag), "analyzed_ids": []}

    if not isinstance(result, dict):
        return {"ok": False, "error": "LLM returned non-object", "select": _select_payload(select_diag), "analyzed_ids": []}

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
    prompt_envelopes = [e for e in context.get("envelopes", []) if isinstance(e, dict)]
    valid_keys = {normalize_thread_key(env.get("subject")) for env in prompt_envelopes}
    valid_refs = _issued_evidence_ids(prompt_envelopes)
    urgent, u_keys, u_refs = _validate_label_rows(urgent, valid_keys=valid_keys, valid_refs=valid_refs)
    pending, p_keys, p_refs = _validate_label_rows(
        pending, valid_keys=valid_keys, valid_refs=valid_refs, owner_action=True,
    )
    sla, s_keys, s_refs = _validate_label_rows(sla, valid_keys=valid_keys, valid_refs=valid_refs)
    evidence_diag = {
        "invalid_thread_keys": u_keys + p_keys + s_keys,
        "invalid_evidence_refs": u_refs + p_refs + s_refs,
    }
    if evidence_diag["invalid_thread_keys"] or evidence_diag["invalid_evidence_refs"]:
        _write_json(phase4_dir / "analysis-diagnostics.json", evidence_diag)
    if merge_mode:
        urgent = _merge_label_rows(
            _load_yaml_rows(phase4_dir / "daily-urgent.yaml", "daily_urgent"),
            urgent,
            analyzed_keys=analyzed_keys,
            window_keys=window_keys,
        )
        pending = _merge_label_rows(
            [
                p for p in _load_yaml_rows(phase4_dir / "pending-replies.yaml", "pending_replies")
                if not p.get("resolved_by_reply")
            ],
            pending,
            analyzed_keys=analyzed_keys,
            window_keys=window_keys,
        )
        sla = _merge_label_rows(
            _load_yaml_rows(phase4_dir / "sla-risks.yaml", "sla_risks"),
            sla,
            analyzed_keys=analyzed_keys,
            window_keys=window_keys,
        )
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

    # weekly-brief-raw.json — daytime patch must not overwrite the nightly brief
    if not merge_mode:
        weekly = result.get("weekly_brief", {})
        if isinstance(weekly, dict):
            weekly["generated_at"] = _now_iso()
            _write_json(phase4_dir / "weekly-brief-raw.json", weekly)

    # Keep the case-lifecycle ledger a derived projection of the rewritten window:
    # a once-closed case stays closed unless the new mail is a valid reopen
    # (guarded inside sync_derived_states).  Fail open so ledger problems never
    # fail an already-successful analysis.
    if not merge_mode:
        try:
            from .case_ledger import sync_derived_states
            sync_derived_states(state_root)
        except Exception:
            pass

    return {
        "ok": True,
        "urgent_count": len(urgent) if isinstance(urgent, list) else 0,
        "pending_count": len(pending) if isinstance(pending, list) else 0,
        "sla_count": len(sla) if isinstance(sla, list) else 0,
        "analyzed_ids": analyzed_ids,
        "diagnostics": evidence_diag,
        "select": _select_payload(select_diag),
    }
