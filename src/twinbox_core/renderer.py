"""Shared artifact rendering for Phase 2-4 outputs."""

from __future__ import annotations

import json
from pathlib import Path

from twinbox_core.artifacts import generated_at, write_lines, yaml_string


def write_json_artifact(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def yaml_header(method: str, model_name: str) -> list[str]:
    return [f'generated_at: "{generated_at()}"', f'method: "{method}"', f'model: "{model_name}"']


def _safe_mermaid_id(value: object) -> str:
    safe = "".join(char if str(char).isascii() and str(char).isalnum() else "_" for char in str(value))
    return safe or "unknown"


def render_phase2_outputs(
    *,
    output_dir: Path,
    doc_dir: Path,
    diagram_dir: Path,
    context: dict[str, object],
    response: dict[str, object],
    model_name: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    doc_dir.mkdir(parents=True, exist_ok=True)
    diagram_dir.mkdir(parents=True, exist_ok=True)

    write_json_artifact(output_dir / "llm-response.json", response)

    persona = response.get("persona_hypotheses", [])
    business = response.get("business_hypotheses", [])
    questions = response.get("confirmation_questions", [])

    persona_lines = yaml_header("llm", model_name) + ["persona_hypotheses:"]
    if isinstance(persona, list):
        for item in persona:
            if not isinstance(item, dict):
                continue
            persona_lines.extend(
                [
                    f"  - id: {item.get('id', 'P?')}",
                    f"    type: {item.get('type', 'unknown')}",
                    f"    confidence: {float(item.get('confidence', 0) or 0):.2f}",
                    f"    hypothesis: {yaml_string(item.get('hypothesis', ''))}",
                    "    evidence:",
                ]
            )
            evidence = item.get("evidence", [])
            if isinstance(evidence, list):
                for entry in evidence:
                    persona_lines.append(f"      - {yaml_string(entry)}")
    write_lines(output_dir / "persona-hypotheses.yaml", persona_lines)

    business_lines = yaml_header("llm", model_name) + ["business_hypotheses:"]
    if isinstance(business, list):
        for item in business:
            if not isinstance(item, dict):
                continue
            business_lines.extend(
                [
                    f"  - id: {item.get('id', 'B?')}",
                    f"    confidence: {float(item.get('confidence', 0) or 0):.2f}",
                    f"    hypothesis: {yaml_string(item.get('hypothesis', ''))}",
                    "    evidence:",
                ]
            )
            evidence = item.get("evidence", [])
            if isinstance(evidence, list):
                for entry in evidence:
                    business_lines.append(f"      - {yaml_string(entry)}")
            business_lines.append("    ai_entry_points:")
            entry_points = item.get("ai_entry_points", [])
            if isinstance(entry_points, list):
                for entry in entry_points:
                    business_lines.append(f"      - {yaml_string(entry)}")
    write_lines(output_dir / "business-hypotheses.yaml", business_lines)

    contacts = context.get("top_contacts", [])
    domains = context.get("top_domains", [])
    relationship_lines = ["graph TD", '  User["Mailbox Owner"]']
    if isinstance(contacts, list):
        for contact in contacts[:8]:
            if not isinstance(contact, dict):
                continue
            key = str(contact.get("key", "unknown"))
            safe = _safe_mermaid_id(key)
            relationship_lines.append(f'  C_{safe}["{key}"]')
            relationship_lines.append(f'  User ---|{contact.get("count", 0)}| C_{safe}')
    if isinstance(domains, list):
        for domain in domains[:3]:
            if not isinstance(domain, dict):
                continue
            key = str(domain.get("key", "unknown"))
            safe = _safe_mermaid_id(key)
            relationship_lines.append(f'  D_{safe}["{key}"]')
            relationship_lines.append(f"  User --> D_{safe}")
    write_lines(diagram_dir / "phase-2-relationship-map.mmd", relationship_lines)

    mailbox_summary = context.get("mailbox_summary", {})
    internal_external = mailbox_summary.get("internal_external", {}) if isinstance(mailbox_summary, dict) else {}
    intent_distribution = context.get("intent_distribution", [])
    intent_summary = ", ".join(
        f"{item.get('key')}({item.get('count')})" for item in intent_distribution if isinstance(item, dict)
    )
    contact_summary = ", ".join(
        f"{item.get('key')}({item.get('count')})" for item in contacts[:5] if isinstance(item, dict)
    )
    domain_summary = ", ".join(
        f"{item.get('key')}({item.get('count')})" for item in domains[:3] if isinstance(item, dict)
    )

    report_lines = [
        "# Phase 2 Report: Persona and Business Profile Inference",
        "",
        "## Method",
        f"- Inference engine: LLM ({model_name})",
        "- Input: Phase 1 census + LLM intent results + 30 enriched body samples",
        f"- Total envelopes in scope: {mailbox_summary.get('total_envelopes', 0) if isinstance(mailbox_summary, dict) else 0}",
        "",
        "## Evidence Base",
        (
            "- Internal vs external: "
            f"internal={internal_external.get('internal', 0)}, "
            f"external={internal_external.get('external', 0)}, "
            f"unknown={internal_external.get('unknown', 0)}"
        ),
        f"- Top intents (LLM): {intent_summary}",
        f"- Top contacts: {contact_summary}",
        f"- Top domains: {domain_summary}",
        "",
        "## Persona Hypotheses",
        "",
    ]
    if isinstance(persona, list):
        for item in persona:
            if not isinstance(item, dict):
                continue
            report_lines.extend(
                [
                    f"### [{item.get('id', 'P?')}] {item.get('type', 'unknown')} (confidence={float(item.get('confidence', 0) or 0):.2f})",
                    "",
                    str(item.get("hypothesis", "")),
                    "",
                    "Evidence:",
                ]
            )
            evidence = item.get("evidence", [])
            if isinstance(evidence, list):
                for entry in evidence:
                    report_lines.append(f"- {entry}")
            report_lines.append("")

    report_lines.extend(["## Business Hypotheses", ""])
    if isinstance(business, list):
        for item in business:
            if not isinstance(item, dict):
                continue
            report_lines.extend(
                [
                    f"### [{item.get('id', 'B?')}] (confidence={float(item.get('confidence', 0) or 0):.2f})",
                    "",
                    str(item.get("hypothesis", "")),
                    "",
                    "Evidence:",
                ]
            )
            evidence = item.get("evidence", [])
            if isinstance(evidence, list):
                for entry in evidence:
                    report_lines.append(f"- {entry}")
            report_lines.extend(["", "AI entry points:"])
            entry_points = item.get("ai_entry_points", [])
            if isinstance(entry_points, list):
                for entry in entry_points:
                    report_lines.append(f"- {entry}")
            report_lines.append("")

    report_lines.extend(["## Confirmation Questions (max 7)", ""])
    if isinstance(questions, list):
        for index, question in enumerate(questions, start=1):
            report_lines.append(f"{index}. {question}")
    report_lines.extend(
        [
            "",
            "## Outputs",
            "- runtime/validation/phase-2/persona-hypotheses.yaml",
            "- runtime/validation/phase-2/business-hypotheses.yaml",
            "- runtime/validation/phase-2/llm-response.json",
            "- docs/validation/phase-2-report.md",
            "- docs/validation/diagrams/phase-2-relationship-map.mmd",
        ]
    )
    write_lines(doc_dir / "phase-2-report.md", report_lines)


def render_phase3_outputs(
    *,
    output_dir: Path,
    doc_dir: Path,
    diagram_dir: Path,
    response: dict[str, object],
    model_name: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    doc_dir.mkdir(parents=True, exist_ok=True)
    diagram_dir.mkdir(parents=True, exist_ok=True)

    write_json_artifact(output_dir / "llm-response.json", response)

    flows = [item for item in response.get("lifecycle_flows", []) if isinstance(item, dict)]
    samples = [item for item in response.get("thread_stage_samples", []) if isinstance(item, dict)]
    phase4_recommendations = [item for item in response.get("phase4_recommendations", []) if isinstance(item, str)]
    policy_suggestions = [item for item in response.get("policy_suggestions", []) if isinstance(item, str)]

    lifecycle_lines = yaml_header("llm", model_name) + ["", "lifecycle_flows:"]
    for flow in flows:
        lifecycle_lines.extend(
            [
                "",
                f"  - id: {flow.get('id', 'LF?')}",
                f"    name: {yaml_string(flow.get('name', ''))}",
                f"    description: {yaml_string(flow.get('description', ''))}",
                "    evidence_threads:",
            ]
        )
        evidence_threads = flow.get("evidence_threads", [])
        if isinstance(evidence_threads, list):
            for entry in evidence_threads:
                lifecycle_lines.append(f"      - {yaml_string(entry)}")
        lifecycle_lines.append("    stages:")
        stages = flow.get("stages", [])
        if isinstance(stages, list):
            for stage in stages:
                if not isinstance(stage, dict):
                    continue
                lifecycle_lines.extend(
                    [
                        f"      - id: {stage.get('id', 'stage')}",
                        f"        name: {yaml_string(stage.get('name', ''))}",
                        f"        entry_signal: {yaml_string(stage.get('entry_signal', ''))}",
                        f"        exit_signal: {yaml_string(stage.get('exit_signal', ''))}",
                        f"        owner_guess: {yaml_string(stage.get('owner_guess', ''))}",
                        f"        waiting_on: {yaml_string(stage.get('waiting_on', ''))}",
                        f"        due_hint: {yaml_string(stage.get('due_hint', ''))}",
                        f"        risk_signal: {yaml_string(stage.get('risk_signal', ''))}",
                        f"        ai_action: {yaml_string(stage.get('ai_action', ''))}",
                    ]
                )
    write_lines(output_dir / "lifecycle-model.yaml", lifecycle_lines)
    write_json_artifact(output_dir / "thread-stage-samples.json", {"samples": samples})

    overview_lines = ["graph TD"]
    for flow in flows:
        flow_id = str(flow.get("id", "LF?"))
        overview_lines.append(f'  {flow_id}["{flow.get("name", flow_id)}"]')
        stages = flow.get("stages", [])
        if not isinstance(stages, list):
            continue
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            stage_id = str(stage.get("id", "stage")).replace("-", "_")
            overview_lines.append(f'  {stage_id}["{stage.get("name", stage.get("id", ""))}"]')
        for index in range(len(stages) - 1):
            current = stages[index]
            nxt = stages[index + 1]
            if not isinstance(current, dict) or not isinstance(nxt, dict):
                continue
            current_id = str(current.get("id", "stage")).replace("-", "_")
            next_id = str(nxt.get("id", "stage")).replace("-", "_")
            overview_lines.append(f"  {current_id} --> {next_id}")
    write_lines(diagram_dir / "phase-3-lifecycle-overview.mmd", overview_lines)

    state_machine_lines = ["stateDiagram-v2"]
    if flows:
        first = flows[0]
        if isinstance(first, dict):
            stages = first.get("stages", [])
            if isinstance(stages, list) and stages:
                first_stage = stages[0]
                if isinstance(first_stage, dict):
                    state_machine_lines.append(
                        f"  [*] --> {str(first_stage.get('id', 'stage')).replace('-', '_')}"
                    )
                for stage in stages:
                    if not isinstance(stage, dict):
                        continue
                    stage_id = str(stage.get("id", "stage")).replace("-", "_")
                    state_machine_lines.append(f"  {stage_id} : {stage.get('name', stage.get('id', ''))}")
                for index in range(len(stages) - 1):
                    current = stages[index]
                    nxt = stages[index + 1]
                    if not isinstance(current, dict) or not isinstance(nxt, dict):
                        continue
                    current_id = str(current.get("id", "stage")).replace("-", "_")
                    next_id = str(nxt.get("id", "stage")).replace("-", "_")
                    state_machine_lines.append(f"  {current_id} --> {next_id}")
                last_stage = stages[-1]
                if isinstance(last_stage, dict):
                    state_machine_lines.append(
                        f"  {str(last_stage.get('id', 'stage')).replace('-', '_')} --> [*]"
                    )
    write_lines(diagram_dir / "phase-3-thread-state-machine.mmd", state_machine_lines)

    report_lines = [
        "# Phase 3 Report: Lifecycle Modeling",
        "",
        "## Method",
        f"- Inference engine: LLM ({model_name})",
        "- Input: Phase 1 census + Phase 2 persona + 20 top threads with body excerpts",
        "",
        "## Lifecycle Flows",
        "",
    ]
    for flow in flows:
        report_lines.extend(
            [
                f"### {flow.get('id', 'LF?')}: {flow.get('name', '')}",
                "",
                str(flow.get("description", "")),
                "",
                "Evidence threads: " + ", ".join(str(item) for item in flow.get("evidence_threads", [])),
                "",
                "| Stage | Name | Entry Signal | Risk Signal | AI Action |",
                "|-------|------|-------------|-------------|-----------|",
            ]
        )
        stages = flow.get("stages", [])
        if isinstance(stages, list):
            for stage in stages:
                if not isinstance(stage, dict):
                    continue
                report_lines.append(
                    "| "
                    + f"{stage.get('id', '')} | {stage.get('name', '')} | "
                    + f"{str(stage.get('entry_signal', ''))[:40]} | "
                    + f"{str(stage.get('risk_signal', ''))[:30]} | "
                    + f"{stage.get('ai_action', '')} |"
                )
        report_lines.append("")

    report_lines.extend(
        [
            "## Thread Stage Samples",
            "",
            "| Thread | Flow | Stage | Confidence | Evidence |",
            "|--------|------|-------|------------|----------|",
        ]
    )
    for sample in samples[:15]:
        report_lines.append(
            "| "
            + f"{str(sample.get('thread_key', ''))[:30]} | {sample.get('flow', '')} | "
            + f"{sample.get('inferred_stage', '')} | {sample.get('confidence', 0)} | "
            + f"{str(sample.get('evidence', ''))[:40]} |"
        )
    report_lines.extend(["", "## Phase 4 Recommendations", ""])
    for recommendation in phase4_recommendations:
        report_lines.append(f"- {recommendation}")
    report_lines.extend(["", "## Policy Suggestions", ""])
    for suggestion in policy_suggestions:
        report_lines.append(f"- {suggestion}")
    report_lines.extend(
        [
            "",
            "## Outputs",
            "- runtime/validation/phase-3/lifecycle-model.yaml",
            "- runtime/validation/phase-3/thread-stage-samples.json",
            "- docs/validation/diagrams/phase-3-lifecycle-overview.mmd",
            "- docs/validation/diagrams/phase-3-thread-state-machine.mmd",
        ]
    )
    write_lines(doc_dir / "phase-3-report.md", report_lines)


def render_phase4_outputs(
    *,
    output_dir: Path,
    doc_dir: Path,
    response: dict[str, object],
    method: str,
    model_name: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    doc_dir.mkdir(parents=True, exist_ok=True)

    urgent = [item for item in response.get("daily_urgent", []) if isinstance(item, dict)]
    pending = [item for item in response.get("pending_replies", []) if isinstance(item, dict)]
    risks = [item for item in response.get("sla_risks", []) if isinstance(item, dict)]
    weekly_brief = response.get("weekly_brief", {})
    if not isinstance(weekly_brief, dict):
        weekly_brief = {}

    write_json_artifact(
        output_dir / "llm-response.json",
        {
            "daily_urgent": urgent,
            "pending_replies": pending,
            "sla_risks": risks,
            "weekly_brief": weekly_brief,
        },
    )

    urgent_lines = yaml_header(method, model_name) + ["daily_urgent:"]
    for item in urgent:
        urgent_lines.extend(
            [
                f"  - thread_key: {yaml_string(item.get('thread_key', ''))}",
                f"    flow: {item.get('flow', 'UNMODELED')}",
                f"    stage: {item.get('stage', 'unknown')}",
                f"    urgency_score: {item.get('urgency_score', 0)}",
                f"    reason_code: {item.get('reason_code', 'unknown')}",
                f"    why: {yaml_string(item.get('why', ''))}",
                f"    action_hint: {yaml_string(item.get('action_hint', ''))}",
                f"    owner: {yaml_string(item.get('owner', ''))}",
                f"    waiting_on: {yaml_string(item.get('waiting_on', ''))}",
                f"    evidence_source: {item.get('evidence_source', 'mail_evidence')}",
            ]
        )
    write_lines(output_dir / "daily-urgent.yaml", urgent_lines)

    pending_lines = yaml_header(method, model_name) + ["pending_replies:"]
    for item in pending:
        pending_lines.extend(
            [
                f"  - thread_key: {yaml_string(item.get('thread_key', ''))}",
                f"    flow: {item.get('flow', 'UNMODELED')}",
                f"    waiting_on_me: {'true' if item.get('waiting_on_me') else 'false'}",
                f"    reason_code: {item.get('reason_code', 'unknown')}",
                f"    why: {yaml_string(item.get('why', ''))}",
                f"    suggested_action: {yaml_string(item.get('suggested_action', ''))}",
                f"    evidence_source: {item.get('evidence_source', 'mail_evidence')}",
            ]
        )
    write_lines(output_dir / "pending-replies.yaml", pending_lines)

    risk_lines = yaml_header(method, model_name) + ["sla_risks:"]
    for item in risks:
        risk_lines.extend(
            [
                f"  - thread_key: {yaml_string(item.get('thread_key', ''))}",
                f"    flow: {item.get('flow', 'UNMODELED')}",
                f"    risk_type: {item.get('risk_type', 'unknown')}",
                f"    risk_description: {yaml_string(item.get('risk_description', ''))}",
                f"    days_since_last_activity: {item.get('days_since_last_activity', 0)}",
                f"    suggested_action: {yaml_string(item.get('suggested_action', ''))}",
            ]
        )
    write_lines(output_dir / "sla-risks.yaml", risk_lines)

    brief_lines = [
        "# Weekly Brief",
        "",
        f"Generated: {generated_at()}",
        f"Model: {model_name}",
        f"Period: {weekly_brief.get('period', 'N/A')}",
        "",
        "## Overview",
        "",
        f"Total threads in window: {weekly_brief.get('total_threads_in_window', 0)}",
        "",
    ]
    material_summary = weekly_brief.get("material_summary", {})
    if isinstance(material_summary, dict) and material_summary:
        brief_lines.extend(["## Material Summary", ""])
        sources = material_summary.get("sources", [])
        if isinstance(sources, list) and sources:
            brief_lines.append(f"Sources: {', '.join(str(item) for item in sources)}")
        source_type = material_summary.get("source_type")
        if source_type:
            brief_lines.append(f"Source type: {source_type}")
        table_title = material_summary.get("table_title")
        if table_title:
            brief_lines.append(f"Title: {table_title}")
        table_section = material_summary.get("table_section")
        if table_section:
            brief_lines.append(f"Section: {table_section}")
        brief_lines.append(f"Period hint: {material_summary.get('period_hint', 'N/A')}")
        brief_lines.append(f"Row count: {material_summary.get('row_count', 0)}")
        headers = material_summary.get("table_headers", [])
        if isinstance(headers, list) and headers:
            brief_lines.append("Headers: " + " | ".join(str(item) for item in headers))
        brief_lines.append("")

        column_stats = material_summary.get("column_stats", [])
        if isinstance(column_stats, list) and column_stats:
            brief_lines.extend(
                [
                    "### Column Stats",
                    "",
                    "| Column | Summary |",
                    "|--------|---------|",
                ]
            )
            for item in column_stats:
                if not isinstance(item, dict):
                    continue
                brief_lines.append(
                    f"| {item.get('column', '')} | {item.get('summary', '')} |"
                )
            brief_lines.append("")

        open_risks = material_summary.get("open_risks", [])
        if isinstance(open_risks, list) and open_risks:
            brief_lines.extend(["### Open Risks", ""])
            for item in open_risks:
                brief_lines.append(f"- {item}")
            brief_lines.append("")

        notes = material_summary.get("notes")
        if notes:
            brief_lines.extend(["### Notes", "", str(notes), ""])
    flow_summary = weekly_brief.get("flow_summary", [])
    if isinstance(flow_summary, list) and flow_summary:
        brief_lines.extend(
            [
                "## Flow Summary",
                "",
                "| Flow | Name | Count | Highlight |",
                "|------|------|-------|-----------|",
            ]
        )
        for item in flow_summary:
            if not isinstance(item, dict):
                continue
            brief_lines.append(
                f"| {item.get('flow', '')} | {item.get('name', '')} | {item.get('count', 0)} | {item.get('highlight', '')} |"
            )
        brief_lines.append("")
    top_actions = weekly_brief.get("top_actions", [])
    if isinstance(top_actions, list) and top_actions:
        brief_lines.extend(["## Top Actions", ""])
        for action in top_actions:
            brief_lines.append(f"- {action}")
        brief_lines.append("")
    action_now = weekly_brief.get("action_now", [])
    if isinstance(action_now, list) and action_now:
        brief_lines.extend(["## Action Now", ""])
        for item in action_now:
            if isinstance(item, dict):
                brief_lines.append(
                    "- "
                    + f"[{item.get('flow', 'UNMODELED')}] "
                    + f"{item.get('thread_key', 'unknown')}: "
                    + f"{item.get('action', '')} ({item.get('why', '')})"
                )
        brief_lines.append("")
    backlog = weekly_brief.get("backlog", [])
    if isinstance(backlog, list) and backlog:
        brief_lines.extend(["## Backlog", ""])
        for item in backlog:
            if isinstance(item, dict):
                brief_lines.append(
                    "- "
                    + f"[{item.get('flow', 'UNMODELED')}] "
                    + f"{item.get('thread_key', 'unknown')}: "
                    + f"{item.get('next_step', '')} ({item.get('why', '')})"
                )
        brief_lines.append("")
    important_changes = weekly_brief.get("important_changes", [])
    if isinstance(important_changes, list) and important_changes:
        brief_lines.extend(["## Important Changes", ""])
        for item in important_changes:
            if isinstance(item, dict):
                brief_lines.append(
                    "- "
                    + f"{item.get('thread_key', 'unknown')}: "
                    + f"{item.get('change', '')} -> {item.get('impact', '')}"
                )
        brief_lines.append("")
    rhythm = weekly_brief.get("rhythm_observation")
    if rhythm:
        brief_lines.extend(["## Rhythm Observation", "", str(rhythm), ""])
    write_lines(output_dir / "weekly-brief.md", brief_lines)

    report_lines = [
        f"# Phase 4 Report{' (Parallel Mode)' if method == 'llm-parallel' else ': Daily Value Outputs'}",
        "",
        "## Method",
        (
            "- 3 parallel LLM calls: urgent+pending, sla-risks, weekly-brief"
            if method == "llm-parallel"
            else f"- Inference engine: LLM ({model_name})"
        ),
        (
            f"- Model: {model_name}"
            if method == "llm-parallel"
            else "- Input: Phase 1 envelopes + Phase 3 lifecycle model + recent thread bodies"
        ),
        "",
        f"## Daily Urgent ({len(urgent)} items)",
        "",
        "| Thread | Flow | Urgency | Action |",
        "|--------|------|---------|--------|",
    ]
    for item in urgent[:10]:
        report_lines.append(
            f"| {str(item.get('thread_key', ''))[:30]} | {item.get('flow', '')} | {item.get('urgency_score', 0)} | {str(item.get('action_hint', ''))[:40]} |"
        )
    report_lines.extend(["", f"## Pending Replies ({len(pending)} items)", ""])
    for item in pending[:5]:
        report_lines.append(f"- {str(item.get('thread_key', ''))[:40]}: {item.get('why', '')}")
    report_lines.extend(["", f"## SLA Risks ({len(risks)} items)", ""])
    for item in risks[:5]:
        report_lines.append(
            f"- [{item.get('risk_type', '')}] {str(item.get('thread_key', ''))[:30]}: {item.get('risk_description', '')}"
        )
    report_lines.extend(
        [
            "",
            "## Outputs",
            "- runtime/validation/phase-4/daily-urgent.yaml",
            "- runtime/validation/phase-4/pending-replies.yaml",
            "- runtime/validation/phase-4/sla-risks.yaml",
            "- runtime/validation/phase-4/weekly-brief.md",
        ]
    )
    write_lines(doc_dir / "phase-4-report.md", report_lines)
