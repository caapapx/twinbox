"""Phase 4 value-output inference and merge core."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from twinbox_core.llm import LLMError, call_llm, clean_json_text, resolve_backend
from twinbox_core.prompt_fragments import (
    base_human_context_rules,
    calibration_rules,
    material_rules,
    urgent_fewshot,
)
from twinbox_core.renderer import render_phase4_outputs

PHASE4_MAILBOX_USER_PREFIX = "## Mailbox data:\n"


def phase4_full_system_prompt() -> str:
    return (
        """You are an enterprise email assistant producing daily actionable outputs for a mailbox owner. Based on the thread data, lifecycle model, and persona below, generate value outputs.

## Your task

Produce a JSON object with this structure:
{
  "daily_urgent": [
    {
      "thread_key": "<thread key>",
      "flow": "<lifecycle flow id or UNMODELED>",
      "stage": "<lifecycle stage id>",
      "urgency_score": <0-100>,
      "reason_code": "<due_soon | waiting_on_me | sla_risk | carry_over | monitor_only>",
      "why": "<one sentence in Chinese explaining urgency>",
      "action_hint": "<concrete next action in Chinese>",
      "owner": "<who should act>",
      "waiting_on": "<who/what is being waited on>",
      "evidence_source": "<mail_evidence | user_declared_rule>"
    }
  ],
  "pending_replies": [
    {
      "thread_key": "<thread key>",
      "flow": "<flow id>",
      "waiting_on_me": true,
      "reason_code": "<waiting_on_me | approval_needed | missing_confirmation>",
      "why": "<why I need to reply, in Chinese>",
      "suggested_action": "<what to do, in Chinese>",
      "evidence_source": "<mail_evidence | user_declared_rule>"
    }
  ],
  "sla_risks": [
    {
      "thread_key": "<thread key>",
      "flow": "<flow id>",
      "risk_type": "<stalled | overdue | no_response | deployment_failure>",
      "risk_description": "<in Chinese>",
      "days_since_last_activity": <number>,
      "suggested_action": "<in Chinese>"
    }
  ],
  "weekly_brief": {
    "period": "<date range>",
    "total_threads_in_window": <number>,
    "action_now": [
      {"thread_key":"<key>", "flow":"<flow>", "why":"<Chinese>", "action":"<Chinese>"}
    ],
    "backlog": [
      {"thread_key":"<key>", "flow":"<flow>", "why":"<Chinese>", "next_step":"<Chinese>"}
    ],
    "important_changes": [
      {"thread_key":"<key>", "change":"<Chinese>", "impact":"<Chinese>"}
    ],
    "flow_summary": [
      {"flow": "<flow id>", "name": "<flow name>", "count": <number>, "highlight": "<key observation in Chinese>"}
    ],
    "top_actions": ["<top 3 actions for this week, in Chinese>"],
    "rhythm_observation": "<one paragraph in Chinese about work rhythm>"
  }
}

## Rules
1. daily_urgent: rank by urgency_score desc. Include threads where action is needed TODAY.
2. pending_replies: only threads where the mailbox owner needs to respond or approve.
3. sla_risks: threads that are stalled, overdue, or have deployment failures.
4. weekly_brief: summarize the lookback window, not just today.
5. Use lifecycle_flow and lifecycle_stage from the thread data to inform your assessment.
6. """
        + base_human_context_rules()
        + """
7. """
        + calibration_rules()
        + """
8. """
        + material_rules()
        + """
9. Mark evidence_source accordingly for items you output.
10. Do NOT invent threads not in the input. Every thread_key must come from the data.
11. Output ONLY the JSON object. No markdown, no explanation.
"""
    )


def phase4_urgent_system_prompt() -> str:
    return (
        """You are an enterprise email assistant. Based on the thread data below, produce a JSON object with exactly two keys:

{
  "daily_urgent": [
    {"thread_key":"<key>","flow":"<flow>","stage":"<stage>","urgency_score":<0-100>,"reason_code":"due_soon|waiting_on_me|sla_risk|carry_over|monitor_only","why":"<Chinese>","action_hint":"<Chinese>","owner":"<who>","waiting_on":"<who>","evidence_source":"mail_evidence|user_declared_rule"}
  ],
  "pending_replies": [
    {"thread_key":"<key>","flow":"<flow>","waiting_on_me":true,"reason_code":"waiting_on_me|approval_needed|missing_confirmation","why":"<Chinese>","suggested_action":"<Chinese>","evidence_source":"mail_evidence|user_declared_rule"}
  ]
}

Rules:
1. daily_urgent: threads needing action TODAY, ranked by urgency_score desc
2. pending_replies: only threads where mailbox owner must respond/approve
3. Use lifecycle_flow/stage from thread data
4. If human_context has manual_facts, override owner/waiting_on guesses
5. """
        + base_human_context_rules()
        + """
6. """
        + calibration_rules()
        + urgent_fewshot()
        + """
7. Every thread_key must come from input data. Output ONLY JSON.
"""
    )


def phase4_sla_system_prompt() -> str:
    return (
        """You are an enterprise email assistant scanning for SLA risks. Produce a JSON object:

{
  "sla_risks": [
    {"thread_key":"<key>","flow":"<flow>","risk_type":"stalled|overdue|no_response|deployment_failure","risk_description":"<Chinese>","days_since_last_activity":<number>,"suggested_action":"<Chinese>"}
  ]
}

Rules:
1. Include threads that are stalled, overdue, or have deployment failures
2. Use lifecycle_flow/stage from thread data to assess risk
3. """
        + base_human_context_rules()
        + """
4. Every thread_key must come from input data. Output ONLY JSON.
"""
    )


def phase4_brief_system_prompt() -> str:
    return (
        """You are an enterprise email assistant producing a weekly brief. Produce a JSON object:

{
  "weekly_brief": {
    "period":"<date range>",
    "total_threads_in_window":<number>,
    "material_summary (OPTIONAL, only if intent=reference)":{
      "sources":["<source name>"],
      "period_hint":"<material date range or N/A>",
      "table_headers":["<header 1>","<header 2>"],
      "row_count":<number>,
      "column_stats":[{"column":"<header>","summary":"<Chinese summary>"}],
      "open_risks":["<Chinese risk bullet>"],
      "notes":"<Chinese note>"
    },
    "action_now":[{"thread_key":"<key>","flow":"<flow>","why":"<Chinese>","action":"<Chinese>"}],
    "backlog":[{"thread_key":"<key>","flow":"<flow>","why":"<Chinese>","next_step":"<Chinese>"}],
    "important_changes":[{"thread_key":"<key>","change":"<Chinese>","impact":"<Chinese>"}],
    "flow_summary":[{"flow":"<id>","name":"<name>","count":<n>,"highlight":"<Chinese>"}],
    "top_actions":["<Chinese action 1>","<Chinese action 2>","<Chinese action 3>"],
    "rhythm_observation":"<one paragraph in Chinese about work rhythm>"
  }
}

Rules:
1. Summarize the entire lookback window, not just today
2. Use lifecycle flows to group threads
3. top_actions: the 3 most important things to do this week
4. rhythm_observation: patterns in email activity timing/volume
5. """
        + base_human_context_rules()
        + """
6. """
        + calibration_rules()
        + """
7. """
        + material_rules()
        + """
8. Prefer threads that reduce missed follow-up, surface items waiting on the owner, or unblock project delivery; demote broadcast/admin/HR/training content unless it clearly needs owner action this week
9. If some material rows (intent=reference only) cannot be mapped to mailbox thread_keys, keep them in material_summary instead of forcing them into action_now/backlog
10. If some material rows cannot be mapped to mailbox thread_keys, keep them in material_summary instead of forcing them into action_now/backlog
11. When a material column contains raw date ranges, preserve the raw ranges or summarize coverage counts; do not invent derived durations unless the counting basis is explicit
12. If the user input includes a shared action candidate list, derive action_now and top_actions from that shared action candidate list instead of inventing a new action-ranked thread order
13. Keep narrative sections (important_changes, flow_summary, rhythm_observation) free to summarize the broader weekly picture even when they mention threads outside the shared action candidate list
14. Output ONLY JSON.
"""
    )


# Back-compat for tests and callers expecting a single string (system + mailbox header only; no JSON payload).
FULL_PROMPT = phase4_full_system_prompt() + PHASE4_MAILBOX_USER_PREFIX
URGENT_PROMPT = phase4_urgent_system_prompt() + PHASE4_MAILBOX_USER_PREFIX
SLA_PROMPT = phase4_sla_system_prompt() + PHASE4_MAILBOX_USER_PREFIX
BRIEF_PROMPT = phase4_brief_system_prompt() + PHASE4_MAILBOX_USER_PREFIX


@dataclass(frozen=True)
class Phase4RunConfig:
    context_path: Path
    output_dir: Path
    doc_dir: Path
    dry_run: bool
    env_file: Path | None
    model_override: str | None
    max_tokens: int


def _parse_markdown_tables(material_notes: str) -> list[dict[str, object]]:
    lines = material_notes.splitlines()
    tables: list[dict[str, object]] = []
    current_source = "uploaded-material"
    current_period = "N/A"
    current_title = ""
    current_section = ""
    index = 0

    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("<!-- ") and line.endswith(" -->"):
            current_source = line[5:-4].strip() or current_source
        elif line.startswith("# 自上传"):
            current_source = line.lstrip("#").strip()
        elif line.startswith("# "):
            current_title = line[2:].strip()
        elif line.startswith("## "):
            current_section = line[3:].strip()
        elif line.startswith("本周：") or line.startswith("周期："):
            current_period = line.split("：", 1)[-1].strip() or current_period

        if (
            line.startswith("|")
            and index + 1 < len(lines)
            and lines[index + 1].strip().startswith("|")
            and "---" in lines[index + 1]
        ):
            header = [cell.strip() for cell in line.strip("|").split("|")]
            rows: list[dict[str, str]] = []
            index += 2
            while index < len(lines):
                row_line = lines[index].strip()
                if not row_line.startswith("|"):
                    break
                cells = [cell.strip() for cell in row_line.strip("|").split("|")]
                if len(cells) < len(header):
                    cells.extend([""] * (len(header) - len(cells)))
                rows.append({header[pos]: cells[pos] for pos in range(len(header))})
                index += 1
            tables.append(
                {
                    "source": current_source,
                    "title": current_title or current_source,
                    "section": current_section or None,
                    "period_hint": current_period,
                    "headers": header,
                    "rows": rows,
                }
            )
            continue
        index += 1

    return tables


def _contains_synthetic_marker(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "非真实数据",
            "合成样例",
            "synthetic",
            "demo only",
            "sample only",
        )
    )


def _is_range_like_value(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    return bool(
        re.search(r"\d{1,2}[-/]\d{1,2}\s*[~至]\s*\d{1,2}[-/]\d{1,2}", stripped)
        or re.search(
            r"\d{4}[-/年]\d{1,2}([-/月]\d{1,2}(日)?)?\s*[~至]\s*\d{4}[-/年]\d{1,2}([-/月]\d{1,2}(日)?)?",
            stripped,
        )
    )


def _summarize_material_column(column: str, values: list[str]) -> str:
    normalized = [value.strip() for value in values if value and value.strip()]
    if not normalized:
        return "无有效值"

    if any(_is_range_like_value(value) for value in normalized):
        sample = "；".join(normalized[:3])
        return f"共{len(normalized)}个原始区间；示例：{sample}"

    if _is_date_like_column(column, normalized):
        return f"{normalized[0]} 至 {normalized[-1]}" if len(normalized) > 1 else normalized[0]

    counts = Counter(normalized)
    average_length = sum(len(value) for value in normalized) / len(normalized)
    if len(counts) <= 6 and average_length <= 18:
        return "，".join(f"{key}={value}" for key, value in counts.items())

    sample = "；".join(normalized[:3])
    return f"非空={len(normalized)}/{len(values)}；示例：{sample}"


def _is_date_like_value(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    return bool(
        re.search(r"\d{4}[-/年]\d{1,2}([-/月]\d{1,2}(日)?)?", stripped)
        or re.search(r"\d{1,2}[-/]\d{1,2}\s*[~至-]\s*\d{1,2}[-/]\d{1,2}", stripped)
    )


def _is_date_like_column(column: str, values: list[str]) -> bool:
    if any(token in column for token in ("日期", "周期", "时间", "起止")):
        return True
    hits = sum(1 for value in values if _is_date_like_value(value))
    return hits >= max(1, len(values) - 1)


def _is_neutral_material_value(value: str) -> bool:
    stripped = value.strip()
    return stripped in {
        "",
        "-",
        "/",
        "无",
        "无。",
        "无问题",
        "通过",
        "已完成",
        "完成",
        "正常",
        "是",
        "否",
        "一次成功",
        "达到预期",
        "待定",
        "n/a",
        "N/A",
    }


def _date_sort_key(value: str) -> tuple[int, ...]:
    stripped = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%Y-%m", "%Y/%m", "%Y年%m月"):
        try:
            parsed = datetime.strptime(stripped, fmt)
            return (parsed.year, parsed.month, parsed.day)
        except ValueError:
            continue

    numbers = [int(token) for token in re.findall(r"\d+", stripped)]
    if len(numbers) >= 3:
        return (numbers[0], numbers[1], numbers[2])
    if len(numbers) == 2:
        return (numbers[0], numbers[1], 1)
    return (9999, 12, 31)


def derive_material_summary(context: dict[str, object]) -> dict[str, object] | None:
    human_context = context.get("human_context", {})
    if not isinstance(human_context, dict):
        return None
    material_notes = human_context.get("material_extracts_notes")
    if not isinstance(material_notes, str) or not material_notes.strip():
        return None

    tables = _parse_markdown_tables(material_notes)
    if not tables:
        return None

    primary = max(tables, key=lambda item: len(item.get("rows", [])) if isinstance(item.get("rows", []), list) else 0)
    headers = [header for header in primary.get("headers", []) if isinstance(header, str)]
    rows = [row for row in primary.get("rows", []) if isinstance(row, dict)]
    if not headers or not rows:
        return None
    is_synthetic = _contains_synthetic_marker(material_notes) or _contains_synthetic_marker(
        str(primary.get("title", "") or "")
    )

    column_stats: list[dict[str, str]] = []
    header_values: dict[str, list[str]] = {}
    for header in headers:
        values = [str(row.get(header, "") or "") for row in rows]
        header_values[header] = values
        if _is_date_like_column(header, [value for value in values if value.strip()]) and not any(
            _is_range_like_value(value) for value in values if value.strip()
        ):
            sorted_values = sorted((value.strip() for value in values if value.strip()), key=_date_sort_key)
            column_stats.append(
                {"column": header, "summary": _summarize_material_column(header, sorted_values)}
            )
            continue
        column_stats.append({"column": header, "summary": _summarize_material_column(header, values)})

    risk_rows: list[str] = []
    row_labels: list[str] = []
    row_prefixes: list[str] = []
    synthetic_markers: list[str] = []
    risk_candidate_headers: set[str] = set()
    for header in headers[1:]:
        values = [value.strip() for value in header_values.get(header, []) if value and value.strip()]
        if not values or _is_date_like_column(header, values):
            continue
        neutral_hits = sum(1 for value in values if _is_neutral_material_value(value))
        average_length = sum(len(value) for value in values) / len(values)
        if neutral_hits > 0 or average_length > 8:
            risk_candidate_headers.add(header)

    for row in rows:
        issue_bits = []
        row_label = "未命名条目"
        for header in headers:
            value = str(row.get(header, "") or "").strip()
            if value:
                row_label = value
                break
        if row_label not in row_labels:
            row_labels.append(row_label)
            coarse_label = re.split(r"[-_（(]", row_label, maxsplit=1)[0].strip()
            if len(coarse_label) >= 2 and coarse_label not in row_prefixes:
                row_prefixes.append(coarse_label)
        for header in headers[1:]:
            if header not in risk_candidate_headers:
                continue
            value = str(row.get(header, "") or "").strip()
            if _is_neutral_material_value(value) or _is_date_like_value(value):
                continue
            if len(value) <= 1:
                continue
            for fragment in re.split(r"[；;，,。]", value):
                cleaned = fragment.strip()
                if len(cleaned) >= 4 and cleaned not in synthetic_markers:
                    synthetic_markers.append(cleaned)
            issue_bits.append(f"{header}={value}")
        if issue_bits:
            risk_rows.append(f"{row_label}: {'；'.join(issue_bits[:3])}")

    sources = []
    for table in tables:
        source = table.get("source")
        if isinstance(source, str) and source and source not in sources:
            sources.append(source)

    return {
        "sources": sources,
        "source_type": "synthetic" if is_synthetic else "uploaded",
        "is_synthetic": is_synthetic,
        "table_title": str(primary.get("title", "") or ""),
        "table_section": primary.get("section"),
        "period_hint": primary.get("period_hint", "N/A"),
        "table_headers": headers,
        "row_labels": row_labels,
        "row_prefixes": row_prefixes,
        "synthetic_markers": synthetic_markers,
        "row_count": len(rows),
        "column_stats": column_stats,
        "open_risks": risk_rows[:5],
        "notes": (
            "该材料标记为非真实/合成样例，仅用于结构化摘要展示；不得直接作为本周事实、行动项或风险结论依据。"
            if is_synthetic
            else "材料摘要直接按上传表格的标题、周期、表头顺序和行数据生成；日期列保留原始范围，枚举列给计数，自由文本列给非空计数和示例。"
        ),
    }


def _normalize_match_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _mentions_any_label(text: str, labels: list[str]) -> bool:
    normalized = _normalize_match_text(text)
    return any(label and _normalize_match_text(label) in normalized for label in labels)


def _strip_synthetic_material_mentions(
    weekly_brief: dict[str, object],
    *,
    row_labels: list[str],
    synthetic_markers: list[str],
) -> None:
    all_markers = [marker for marker in [*row_labels, *synthetic_markers] if marker]
    top_actions = weekly_brief.get("top_actions", [])
    if isinstance(top_actions, list):
        weekly_brief["top_actions"] = [
            item
            for item in top_actions
            if isinstance(item, str) and not _mentions_any_label(item, all_markers)
        ]

    for section_name, fields in (
        ("action_now", ("thread_key", "why", "action")),
        ("backlog", ("thread_key", "why", "next_step")),
        ("important_changes", ("thread_key", "change", "impact")),
    ):
        items = weekly_brief.get(section_name, [])
        if not isinstance(items, list):
            continue
        filtered_items: list[dict[str, object]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            thread_key = str(item.get("thread_key", "") or "")
            text_blob = " ".join(str(item.get(field, "") or "") for field in fields)
            if not _mentions_any_label(text_blob, all_markers):
                filtered_items.append(item)
                continue
            if thread_key and _mentions_any_label(thread_key, all_markers):
                filtered_items.append(item)
        weekly_brief[section_name] = filtered_items


def _ensure_material_summary(
    response: dict[str, object],
    *,
    context: dict[str, object],
) -> dict[str, object]:
    # Check if all materials are template_hint (skip material_summary for templates)
    human_context = context.get("human_context", {})
    if isinstance(human_context, dict):
        material_notes = human_context.get("material_extracts_notes", "")
        if isinstance(material_notes, str):
            import re
            intent_tags = re.findall(r'intent=(\w+)', material_notes)
            if intent_tags and all(intent == "template_hint" for intent in intent_tags):
                return response

    derived = derive_material_summary(context)
    if not derived:
        return response

    weekly_brief = response.get("weekly_brief", {})
    if not isinstance(weekly_brief, dict):
        weekly_brief = {}
        response["weekly_brief"] = weekly_brief

    existing = weekly_brief.get("material_summary")
    merged_summary = existing.copy() if isinstance(existing, dict) else {}
    merged_summary.update(derived)
    weekly_brief["material_summary"] = merged_summary

    if bool(derived.get("is_synthetic")):
        _strip_synthetic_material_mentions(
            weekly_brief,
            row_labels=[
                label
                for label in [
                    *derived.get("row_labels", []),
                    *derived.get("row_prefixes", []),
                ]
                if isinstance(label, str)
            ],
            synthetic_markers=[
                marker for marker in derived.get("synthetic_markers", []) if isinstance(marker, str)
            ],
        )
    return response


def _load_object(path: Path) -> dict[str, object]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise LLMError(f"Expected JSON object in {path}")
    return parsed


def _filter_skip_threads(context: dict[str, object]) -> None:
    if "threads" in context and isinstance(context["threads"], list):
        filtered_threads = [t for t in context["threads"] if isinstance(t, dict) and not t.get("skip_phase4")]
        context["threads"] = filtered_threads
        context["thread_candidates"] = len(filtered_threads)


def _parse_response(raw: str, expected_key: str | None = None) -> dict[str, object]:
    try:
        parsed = json.loads(clean_json_text(raw))
    except (json.JSONDecodeError, LLMError) as e:
        # Fallback for severely truncated JSON
        print(f"Warning: JSON parse failed, attempting aggressive repair: {e}")
        # Use raw text and try to fix it manually since clean_json_text failed
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        
        # very aggressive repair for truncated JSON
        if cleaned.rfind('"') > cleaned.rfind('}') and cleaned.rfind('"') > cleaned.rfind(']'):
             cleaned += '"'
             
        # if the last character is a string but doesn't have a closing quote
        elif cleaned.endswith('"') and not cleaned.endswith('\\"'):
             pass # it's closed
        elif cleaned.rfind('"') % 2 != 0:
             cleaned += '"'
             
        # Add missing commas or values if it ends abruptly
        cleaned_stripped = cleaned.strip()
        if cleaned_stripped.endswith(':'):
            cleaned = cleaned_stripped + '""'
        elif cleaned_stripped.endswith(','):
            cleaned = cleaned_stripped[:-1]
            
        while cleaned.count("[") > cleaned.count("]"):
            cleaned += "]"
        while cleaned.count("{") > cleaned.count("}"):
            cleaned += "}"
            
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            # One more attempt: try to fix missing quotes around keys or values
            import re
            cleaned = re.sub(r'(\w+):', r'"\1":', cleaned)
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                print(f"Error: Could not repair JSON. Raw output: {raw[:500]}")
                raise LLMError(f"Failed to parse LLM output as JSON: {e}")
            
    if not isinstance(parsed, dict):
        raise LLMError("Expected a JSON object from Phase 4 response")
    if expected_key and expected_key not in parsed:
        raise LLMError(f"Phase 4 response missing key: {expected_key}")
    return parsed


def _resolve_model(env_file: Path | None, model_override: str | None) -> str:
    if model_override:
        return model_override
    try:
        return resolve_backend(env_file=env_file).model
    except LLMError:
        return "unknown"


def _call_with_prompt(
    *,
    system_prompt: str,
    user_prefix: str,
    context_path: Path,
    extra_user_content: str = "",
    env_file: Path | None,
    model_override: str | None,
    max_tokens: int,
) -> dict[str, object]:
    user_content = user_prefix + context_path.read_text(encoding="utf-8")
    if extra_user_content:
        user_content += extra_user_content
    return _parse_response(
        call_llm(
            user_content,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            env_file=env_file,
            model_override=model_override,
        )
    )


def _apply_recipient_role_weights(
    response: dict[str, object],
    context_path: Path,
) -> dict[str, object]:
    """Apply urgency multiplier for non-direct threads.

    Loads recipient_role from context ``threads`` (Phase 4 pack), else ``top_threads``, else Phase 3 pack.
    Multipliers: cc_only/indirect 0.6, group_only 0.4.
    """
    try:
        context = _load_object(context_path)
    except Exception:
        return response

    top_threads = context.get("threads", []) if isinstance(context, dict) else []
    if not isinstance(top_threads, list) or not top_threads:
        top_threads = context.get("top_threads", []) if isinstance(context, dict) else []
    if not isinstance(top_threads, list) or not top_threads:
        phase3_context_path = context_path.parent.parent / "phase-3" / "context-pack.json"
        try:
            phase3_context = _load_object(phase3_context_path)
        except Exception:
            phase3_context = {}
        top_threads = phase3_context.get("top_threads", []) if isinstance(phase3_context, dict) else []

    ROLE_WEIGHTS: dict[str, float] = {
        "cc_only": 0.6,
        "indirect": 0.6,
        "group_only": 0.4,
    }

    role_map: dict[str, str] = {}
    for thread in top_threads:
        if not isinstance(thread, dict):
            continue
        role = str(thread.get("recipient_role", "") or "")
        if role in ROLE_WEIGHTS:
            key = str(thread.get("thread_key", "") or "")
            if key:
                role_map[key] = role

    if not role_map:
        return response

    daily_urgent = response.get("daily_urgent", [])
    if isinstance(daily_urgent, list):
        for item in daily_urgent:
            if not isinstance(item, dict):
                continue
            tkey = str(item.get("thread_key", "") or "")
            role = role_map.get(tkey)
            if role is not None:
                score = item.get("urgency_score")
                if isinstance(score, (int, float)):
                    item["urgency_score"] = round(score * ROLE_WEIGHTS[role])
                item["recipient_role"] = role

    pending_replies = response.get("pending_replies", [])
    if isinstance(pending_replies, list):
        for item in pending_replies:
            if not isinstance(item, dict):
                continue
            tkey = str(item.get("thread_key", "") or "")
            role = role_map.get(tkey)
            if role is not None:
                item["recipient_role"] = role

    return response


def _build_action_candidates(response: dict[str, object]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    seen_thread_keys: set[str] = set()

    for item in response.get("daily_urgent", []):
        if not isinstance(item, dict):
            continue
        thread_key = str(item.get("thread_key", "") or "")
        if not thread_key or thread_key in seen_thread_keys:
            continue
        seen_thread_keys.add(thread_key)
        candidates.append(
            {
                "thread_key": thread_key,
                "urgency_score": item.get("urgency_score", 0) if isinstance(item.get("urgency_score"), (int, float)) else 0,
                "reason_code": str(item.get("reason_code", "") or ""),
                "why": str(item.get("why", "") or ""),
                "action_hint": str(item.get("action_hint", "") or ""),
            }
        )

    for item in response.get("pending_replies", []):
        if not isinstance(item, dict):
            continue
        thread_key = str(item.get("thread_key", "") or "")
        if not thread_key or thread_key in seen_thread_keys:
            continue
        seen_thread_keys.add(thread_key)
        candidates.append(
            {
                "thread_key": thread_key,
                "urgency_score": 0,
                "reason_code": str(item.get("reason_code", "") or ""),
                "why": str(item.get("why", "") or ""),
                "action_hint": str(item.get("suggested_action", "") or ""),
            }
        )

    return candidates


def _write_action_candidates(output_dir: Path, response: dict[str, object]) -> None:
    payload = {"action_candidates": _build_action_candidates(response)}
    (output_dir / "action-candidates.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _render_action_candidates_prompt_block(output_dir: Path) -> str:
    path = output_dir / "action-candidates.json"
    if not path.is_file():
        return ""
    try:
        payload = _load_object(path)
    except Exception:
        return ""

    candidates = payload.get("action_candidates", [])
    if not isinstance(candidates, list) or not candidates:
        return ""

    lines = [
        "\n\n## Shared action candidates:",
        "Use this shared action candidate list for weekly action-ranked fields (`action_now`, `top_actions`).",
    ]
    for item in candidates[:10]:
        if not isinstance(item, dict):
            continue
        lines.append(
            "- "
            + f"{item.get('thread_key', '')} | "
            + f"score={item.get('urgency_score', 0)} | "
            + f"reason={item.get('reason_code', '')} | "
            + f"why={item.get('why', '')} | "
            + f"action={item.get('action_hint', '')}"
        )
    return "\n".join(lines)


def run_single(config: Phase4RunConfig) -> dict[str, object]:
    context = _load_object(config.context_path)
    had_threads = "threads" in context and isinstance(context["threads"], list)
    _filter_skip_threads(context)
    filtered_text = (
        json.dumps(context, ensure_ascii=False)
        if had_threads
        else config.context_path.read_text(encoding="utf-8")
    )

    if config.dry_run:
        system_prompt = phase4_full_system_prompt()
        user_blob = PHASE4_MAILBOX_USER_PREFIX + filtered_text
        print(f"=== SYSTEM length: {len(system_prompt)} chars ===")
        print(f"=== USER length: {len(user_blob)} chars ===")
        thread_count = len(context["threads"]) if had_threads else 0
        print(f"=== threads after filter: {thread_count} ===")
        print("=== DRY RUN ===")
        return {"dry_run": True}

    config.output_dir.mkdir(parents=True, exist_ok=True)
    backend = resolve_backend(env_file=config.env_file)
    model_name = config.model_override or backend.model

    if had_threads:
        filtered_context_path = config.output_dir / "context-pack-filtered-single.json"
        filtered_context_path.write_text(filtered_text, encoding="utf-8")
        prompt_context_path = filtered_context_path
    else:
        prompt_context_path = config.context_path

    print(f"LLM backend: {backend.backend} ({backend.model})")
    print("Calling LLM for daily value outputs...")
    response = _call_with_prompt(
        system_prompt=phase4_full_system_prompt(),
        user_prefix=PHASE4_MAILBOX_USER_PREFIX,
        context_path=prompt_context_path,
        env_file=config.env_file,
        model_override=config.model_override,
        max_tokens=config.max_tokens,
    )
    response = _ensure_material_summary(response, context=context)
    response = _apply_recipient_role_weights(response, config.context_path)
    print("LLM response saved.")
    print("Generating Phase 4 outputs...")
    render_phase4_outputs(
        output_dir=config.output_dir,
        doc_dir=config.doc_dir,
        response=response,
        method="llm",
        model_name=model_name,
    )
    print(f"Phase 4 outputs generated: {len(response.get('daily_urgent', []))} urgent, {len(response.get('pending_replies', []))} pending, {len(response.get('sla_risks', []))} risks")
    print("")
    print("Phase 4 thinking complete.")
    return response


def run_subtask(
    *,
    kind: str,
    context_path: Path,
    output_dir: Path,
    env_file: Path | None,
    model_override: str | None,
) -> dict[str, object]:
    context = _load_object(context_path)
    had_threads = "threads" in context and isinstance(context["threads"], list)
    _filter_skip_threads(context)

    if had_threads:
        output_dir.mkdir(parents=True, exist_ok=True)
        filtered_context_path = output_dir / f"context-pack-filtered-{kind}.json"
        filtered_context_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
        prompt_context_path = filtered_context_path
    else:
        prompt_context_path = context_path

    backend = resolve_backend(env_file=env_file)
    print(f"LLM backend: {backend.backend} ({backend.model})")

    if kind == "urgent":
        response = _call_with_prompt(
            system_prompt=phase4_urgent_system_prompt(),
            user_prefix=PHASE4_MAILBOX_USER_PREFIX,
            context_path=prompt_context_path,
            env_file=env_file,
            model_override=model_override,
            max_tokens=4096,
        )
        response = _apply_recipient_role_weights(response, context_path)
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_action_candidates(output_dir, response)
        target = output_dir / "urgent-pending-raw.json"
        label = "urgent+pending"
    elif kind == "sla":
        response = _call_with_prompt(
            system_prompt=phase4_sla_system_prompt(),
            user_prefix=PHASE4_MAILBOX_USER_PREFIX,
            context_path=prompt_context_path,
            env_file=env_file,
            model_override=model_override,
            max_tokens=2048,
        )
        target = output_dir / "sla-risks-raw.json"
        label = "sla-risks"
    elif kind == "brief":
        response = _call_with_prompt(
            system_prompt=phase4_brief_system_prompt(),
            user_prefix=PHASE4_MAILBOX_USER_PREFIX,
            context_path=prompt_context_path,
            extra_user_content=_render_action_candidates_prompt_block(output_dir),
            env_file=env_file,
            model_override=model_override,
            max_tokens=2048,
        )
        target = output_dir / "weekly-brief-raw.json"
        label = "weekly-brief"
    else:
        raise LLMError(f"Unknown Phase 4 subtask: {kind}")

    if kind == "brief":
        response = _ensure_material_summary(response, context=context)

    output_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{label} done: {target}")
    return response


def merge_phase4_outputs(
    *,
    output_dir: Path,
    doc_dir: Path,
    env_file: Path | None,
    model_override: str | None,
) -> dict[str, object]:
    required = {
        "urgent-pending-raw.json": ("daily_urgent", "pending_replies"),
        "sla-risks-raw.json": ("sla_risks",),
        "weekly-brief-raw.json": ("weekly_brief",),
    }
    loaded: dict[str, dict[str, object]] = {}
    for filename in required:
        path = output_dir / filename
        if not path.is_file():
            raise LLMError(f"Missing {filename}. Run think sub-tasks first.")
        loaded[filename] = _load_object(path)

    merged = {
        "daily_urgent": loaded["urgent-pending-raw.json"].get("daily_urgent", []),
        "pending_replies": loaded["urgent-pending-raw.json"].get("pending_replies", []),
        "sla_risks": loaded["sla-risks-raw.json"].get("sla_risks", []),
        "weekly_brief": loaded["weekly-brief-raw.json"].get("weekly_brief", {}),
    }
    render_phase4_outputs(
        output_dir=output_dir,
        doc_dir=doc_dir,
        response=merged,
        method="llm-parallel",
        model_name=_resolve_model(env_file, model_override),
    )
    print(
        f"Merged: {len(merged.get('daily_urgent', []))} urgent, {len(merged.get('pending_replies', []))} pending, {len(merged.get('sla_risks', []))} risks"
    )
    print("")
    print("Phase 4 merge complete.")
    print("Outputs:")
    print(f"  {output_dir / 'daily-urgent.yaml'}")
    print(f"  {output_dir / 'pending-replies.yaml'}")
    print(f"  {output_dir / 'sla-risks.yaml'}")
    print(f"  {output_dir / 'weekly-brief.md'}")
    print(f"  {doc_dir / 'phase-4-report.md'}")
    return merged


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    single = subparsers.add_parser("single-run")
    single.add_argument("--context", required=True)
    single.add_argument("--output-dir", required=True)
    single.add_argument("--doc-dir", required=True)
    single.add_argument("--env-file")
    single.add_argument("--model")
    single.add_argument("--dry-run", action="store_true")
    single.add_argument("--max-tokens", type=int, default=8192)

    urgent = subparsers.add_parser("think-urgent")
    urgent.add_argument("--context", required=True)
    urgent.add_argument("--output-dir", required=True)
    urgent.add_argument("--env-file")
    urgent.add_argument("--model")

    sla = subparsers.add_parser("think-sla")
    sla.add_argument("--context", required=True)
    sla.add_argument("--output-dir", required=True)
    sla.add_argument("--env-file")
    sla.add_argument("--model")

    brief = subparsers.add_parser("think-brief")
    brief.add_argument("--context", required=True)
    brief.add_argument("--output-dir", required=True)
    brief.add_argument("--env-file")
    brief.add_argument("--model")

    merge = subparsers.add_parser("merge")
    merge.add_argument("--output-dir", required=True)
    merge.add_argument("--doc-dir", required=True)
    merge.add_argument("--env-file")
    merge.add_argument("--model")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        env_file = Path(args.env_file).expanduser() if getattr(args, "env_file", None) else None

        if args.command == "single-run":
            run_single(
                Phase4RunConfig(
                    context_path=Path(args.context).expanduser(),
                    output_dir=Path(args.output_dir).expanduser(),
                    doc_dir=Path(args.doc_dir).expanduser(),
                    dry_run=args.dry_run,
                    env_file=env_file,
                    model_override=args.model,
                    max_tokens=args.max_tokens,
                )
            )
            return 0

        if args.command == "think-urgent":
            run_subtask(
                kind="urgent",
                context_path=Path(args.context).expanduser(),
                output_dir=Path(args.output_dir).expanduser(),
                env_file=env_file,
                model_override=args.model,
            )
            return 0

        if args.command == "think-sla":
            run_subtask(
                kind="sla",
                context_path=Path(args.context).expanduser(),
                output_dir=Path(args.output_dir).expanduser(),
                env_file=env_file,
                model_override=args.model,
            )
            return 0

        if args.command == "think-brief":
            run_subtask(
                kind="brief",
                context_path=Path(args.context).expanduser(),
                output_dir=Path(args.output_dir).expanduser(),
                env_file=env_file,
                model_override=args.model,
            )
            return 0

        if args.command == "merge":
            merge_phase4_outputs(
                output_dir=Path(args.output_dir).expanduser(),
                doc_dir=Path(args.doc_dir).expanduser(),
                env_file=env_file,
                model_override=args.model,
            )
            return 0
    except (LLMError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
