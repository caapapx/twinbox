"""Phase 3 lifecycle modeling core."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from twinbox_core.artifacts import generated_at, write_lines, yaml_string
from twinbox_core.llm import LLMError, call_llm, clean_json_text, resolve_backend


@dataclass(frozen=True)
class Phase3RunConfig:
    context_path: Path
    output_dir: Path
    doc_dir: Path
    diagram_dir: Path
    dry_run: bool
    env_file: Path | None
    model_override: str | None


def build_prompt(context_text: str) -> str:
    return """You are an enterprise email workflow analyst. Based on the mailbox data, persona hypotheses, and thread summaries below, build a thread-level lifecycle model.

## Your task

Produce a JSON object with this structure:
{
  "lifecycle_flows": [
    {
      "id": "LF1",
      "name": "<flow name in Chinese>",
      "description": "<one sentence in Chinese>",
      "evidence_threads": ["<thread_key(count)>", "..."],
      "stages": [
        {
          "id": "LF1-S1",
          "name": "<stage name in Chinese>",
          "entry_signal": "<what triggers entry, in Chinese>",
          "exit_signal": "<what triggers exit>",
          "owner_guess": "<who owns this stage>",
          "waiting_on": "<who/what is being waited on>",
          "due_hint": "<typical deadline pattern>",
          "risk_signal": "<what indicates risk>",
          "ai_action": "<summarize|classify|remind|draft — pick 1-2>"
        }
      ]
    }
  ],
  "thread_stage_samples": [
    {
      "thread_key": "<from top_threads>",
      "flow": "LF1",
      "inferred_stage": "LF1-S3",
      "stage_name": "<stage name>",
      "evidence": "<why this stage, referencing email content>",
      "confidence": 0.82,
      "ai_action": "<recommended action>"
    }
  ],
  "phase4_recommendations": [
    "<which 2 flows are most ready for Phase 4 value output, and why>"
  ],
  "policy_suggestions": [
    "<max 5 suggestions for config/profiles/rules>"
  ]
}

## Rules
1. Identify 3-5 lifecycle flows from the data. Do NOT predefine business types — derive them from evidence.
2. Each flow must have at least 4 stages with entry/exit signals.
3. thread_stage_samples: classify each of the top_threads into a flow+stage. If a thread does not fit any flow, mark flow as "UNMODELED".
4. Every evidence and signal must reference concrete thread_keys, subjects, or patterns from the input.
5. If human_context is provided:
   - Use manual_facts to correct owner_guess and waiting_on
   - Use manual_habits to inject periodic tasks as a separate flow or stage
   - Mark evidence source: "mail_evidence" vs "user_declared_rule"
6. Confidence must reflect actual certainty.
7. Output ONLY the JSON object. No markdown, no explanation.

## Mailbox data:
""" + context_text


def _load_object(path: Path) -> dict[str, object]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise LLMError(f"Expected JSON object in {path}")
    return parsed


def _parse_response(raw: str) -> dict[str, object]:
    parsed = json.loads(clean_json_text(raw))
    if not isinstance(parsed, dict):
        raise LLMError("Expected a JSON object from Phase 3 response")
    return parsed


def _write_lifecycle_overview(path: Path, flows: list[dict[str, object]]) -> None:
    lines = ["graph TD"]
    for flow in flows:
        flow_id = str(flow.get("id", "LF?"))
        lines.append(f'  {flow_id}["{flow.get("name", flow_id)}"]')
        stages = flow.get("stages", [])
        if not isinstance(stages, list):
            continue
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            stage_id = str(stage.get("id", "stage")).replace("-", "_")
            lines.append(f'  {stage_id}["{stage.get("name", stage.get("id", ""))}"]')
        for index in range(len(stages) - 1):
            current = stages[index]
            nxt = stages[index + 1]
            if not isinstance(current, dict) or not isinstance(nxt, dict):
                continue
            current_id = str(current.get("id", "stage")).replace("-", "_")
            next_id = str(nxt.get("id", "stage")).replace("-", "_")
            lines.append(f"  {current_id} --> {next_id}")
    write_lines(path, lines)


def _write_state_machine(path: Path, flows: list[dict[str, object]]) -> None:
    lines = ["stateDiagram-v2"]
    if flows:
        first = flows[0]
        if isinstance(first, dict):
            stages = first.get("stages", [])
            if isinstance(stages, list) and stages:
                first_stage = stages[0]
                if isinstance(first_stage, dict):
                    lines.append(f"  [*] --> {str(first_stage.get('id', 'stage')).replace('-', '_')}")
                for stage in stages:
                    if not isinstance(stage, dict):
                        continue
                    stage_id = str(stage.get("id", "stage")).replace("-", "_")
                    lines.append(f"  {stage_id} : {stage.get('name', stage.get('id', ''))}")
                for index in range(len(stages) - 1):
                    current = stages[index]
                    nxt = stages[index + 1]
                    if not isinstance(current, dict) or not isinstance(nxt, dict):
                        continue
                    current_id = str(current.get("id", "stage")).replace("-", "_")
                    next_id = str(nxt.get("id", "stage")).replace("-", "_")
                    lines.append(f"  {current_id} --> {next_id}")
                last_stage = stages[-1]
                if isinstance(last_stage, dict):
                    lines.append(f"  {str(last_stage.get('id', 'stage')).replace('-', '_')} --> [*]")
    write_lines(path, lines)


def run_phase3_lifecycle(config: Phase3RunConfig) -> dict[str, object]:
    context = _load_object(config.context_path)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.doc_dir.mkdir(parents=True, exist_ok=True)
    config.diagram_dir.mkdir(parents=True, exist_ok=True)

    prompt = build_prompt(config.context_path.read_text(encoding="utf-8"))
    if config.dry_run:
        print(f"=== PROMPT length: {len(prompt)} chars ===")
        print("=== DRY RUN ===")
        return {"dry_run": True}

    backend = resolve_backend(env_file=config.env_file)
    model_name = config.model_override or backend.model
    print(f"LLM backend: {backend.backend} ({backend.model})")
    print("Calling LLM for lifecycle modeling...")
    response = _parse_response(
        call_llm(
            prompt,
            max_tokens=8192,
            env_file=config.env_file,
            model_override=config.model_override,
        )
    )

    llm_response_path = config.output_dir / "llm-response.json"
    llm_response_path.write_text(
        json.dumps(response, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("LLM response saved.")
    print("Generating Phase 3 outputs...")

    flows = [item for item in response.get("lifecycle_flows", []) if isinstance(item, dict)]
    samples = [item for item in response.get("thread_stage_samples", []) if isinstance(item, dict)]
    phase4_recommendations = [
        item for item in response.get("phase4_recommendations", []) if isinstance(item, str)
    ]
    policy_suggestions = [item for item in response.get("policy_suggestions", []) if isinstance(item, str)]

    lifecycle_lines = [
        f'generated_at: "{generated_at()}"',
        'method: "llm"',
        f'model: "{model_name}"',
        "",
        "lifecycle_flows:",
    ]
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
    write_lines(config.output_dir / "lifecycle-model.yaml", lifecycle_lines)
    (config.output_dir / "thread-stage-samples.json").write_text(
        json.dumps({"samples": samples}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_lifecycle_overview(config.diagram_dir / "phase-3-lifecycle-overview.mmd", flows)
    _write_state_machine(config.diagram_dir / "phase-3-thread-state-machine.mmd", flows)

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
    write_lines(config.doc_dir / "phase-3-report.md", report_lines)
    print("Phase 3 outputs generated.")
    print("")
    print("Phase 3 thinking complete.")
    print("Outputs:")
    print(f"  {config.output_dir / 'lifecycle-model.yaml'}")
    print(f"  {config.output_dir / 'thread-stage-samples.json'}")
    print(f"  {config.doc_dir / 'phase-3-report.md'}")
    print(f"  {config.diagram_dir / 'phase-3-lifecycle-overview.mmd'}")
    print(f"  {config.diagram_dir / 'phase-3-thread-state-machine.mmd'}")
    return response


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--doc-dir", required=True)
    parser.add_argument("--diagram-dir", required=True)
    parser.add_argument("--env-file")
    parser.add_argument("--model")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        run_phase3_lifecycle(
            Phase3RunConfig(
                context_path=Path(args.context).expanduser(),
                output_dir=Path(args.output_dir).expanduser(),
                doc_dir=Path(args.doc_dir).expanduser(),
                diagram_dir=Path(args.diagram_dir).expanduser(),
                dry_run=args.dry_run,
                env_file=Path(args.env_file).expanduser() if args.env_file else None,
                model_override=args.model,
            )
        )
    except (LLMError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
