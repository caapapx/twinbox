"""Phase 4 value-output inference and merge core."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from twinbox_core.llm import LLMError, call_llm, clean_json_text, resolve_backend
from twinbox_core.renderer import render_phase4_outputs


FULL_PROMPT = """You are an enterprise email assistant producing daily actionable outputs for a mailbox owner. Based on the thread data, lifecycle model, and persona below, generate value outputs.

## Your task

Produce a JSON object with this structure:
{
  "daily_urgent": [
    {
      "thread_key": "<thread key>",
      "flow": "<lifecycle flow id or UNMODELED>",
      "stage": "<lifecycle stage id>",
      "urgency_score": <0-100>,
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
6. If human_context is provided:
   - manual_facts override owner/waiting_on guesses
   - manual_habits inject periodic tasks into daily_urgent or weekly_brief
   - Mark evidence_source accordingly
7. Do NOT invent threads not in the input. Every thread_key must come from the data.
8. Output ONLY the JSON object. No markdown, no explanation.

## Mailbox data:
"""

URGENT_PROMPT = """You are an enterprise email assistant. Based on the thread data below, produce a JSON object with exactly two keys:

{
  "daily_urgent": [
    {"thread_key":"<key>","flow":"<flow>","stage":"<stage>","urgency_score":<0-100>,"why":"<Chinese>","action_hint":"<Chinese>","owner":"<who>","waiting_on":"<who>","evidence_source":"mail_evidence|user_declared_rule"}
  ],
  "pending_replies": [
    {"thread_key":"<key>","flow":"<flow>","waiting_on_me":true,"why":"<Chinese>","suggested_action":"<Chinese>","evidence_source":"mail_evidence|user_declared_rule"}
  ]
}

Rules:
1. daily_urgent: threads needing action TODAY, ranked by urgency_score desc
2. pending_replies: only threads where mailbox owner must respond/approve
3. Use lifecycle_flow/stage from thread data
4. If human_context has manual_facts, override owner/waiting_on guesses
5. Every thread_key must come from input data. Output ONLY JSON.

Mailbox data:
"""

SLA_PROMPT = """You are an enterprise email assistant scanning for SLA risks. Produce a JSON object:

{
  "sla_risks": [
    {"thread_key":"<key>","flow":"<flow>","risk_type":"stalled|overdue|no_response|deployment_failure","risk_description":"<Chinese>","days_since_last_activity":<number>,"suggested_action":"<Chinese>"}
  ]
}

Rules:
1. Include threads that are stalled, overdue, or have deployment failures
2. Use lifecycle_flow/stage from thread data to assess risk
3. Every thread_key must come from input data. Output ONLY JSON.

Mailbox data:
"""

BRIEF_PROMPT = """You are an enterprise email assistant producing a weekly brief. Produce a JSON object:

{
  "weekly_brief": {
    "period":"<date range>",
    "total_threads_in_window":<number>,
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
5. Output ONLY JSON.

Mailbox data:
"""


@dataclass(frozen=True)
class Phase4RunConfig:
    context_path: Path
    output_dir: Path
    doc_dir: Path
    dry_run: bool
    env_file: Path | None
    model_override: str | None
    max_tokens: int


def _load_object(path: Path) -> dict[str, object]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise LLMError(f"Expected JSON object in {path}")
    return parsed


def _parse_response(raw: str, expected_key: str | None = None) -> dict[str, object]:
    parsed = json.loads(clean_json_text(raw))
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
    prompt_prefix: str,
    context_path: Path,
    env_file: Path | None,
    model_override: str | None,
    max_tokens: int,
) -> dict[str, object]:
    prompt = prompt_prefix + context_path.read_text(encoding="utf-8")
    return _parse_response(
        call_llm(
            prompt,
            max_tokens=max_tokens,
            env_file=env_file,
            model_override=model_override,
        )
    )


def run_single(config: Phase4RunConfig) -> dict[str, object]:
    if config.dry_run:
        prompt = FULL_PROMPT + config.context_path.read_text(encoding="utf-8")
        print(f"=== PROMPT length: {len(prompt)} chars ===")
        print("=== DRY RUN ===")
        return {"dry_run": True}

    backend = resolve_backend(env_file=config.env_file)
    model_name = config.model_override or backend.model
    print(f"LLM backend: {backend.backend} ({backend.model})")
    print("Calling LLM for daily value outputs...")
    response = _call_with_prompt(
        prompt_prefix=FULL_PROMPT,
        context_path=config.context_path,
        env_file=config.env_file,
        model_override=config.model_override,
        max_tokens=config.max_tokens,
    )
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
    backend = resolve_backend(env_file=env_file)
    print(f"LLM backend: {backend.backend} ({backend.model})")

    if kind == "urgent":
        response = _call_with_prompt(
            prompt_prefix=URGENT_PROMPT,
            context_path=context_path,
            env_file=env_file,
            model_override=model_override,
            max_tokens=4096,
        )
        target = output_dir / "urgent-pending-raw.json"
        label = "urgent+pending"
    elif kind == "sla":
        response = _call_with_prompt(
            prompt_prefix=SLA_PROMPT,
            context_path=context_path,
            env_file=env_file,
            model_override=model_override,
            max_tokens=2048,
        )
        target = output_dir / "sla-risks-raw.json"
        label = "sla-risks"
    elif kind == "brief":
        response = _call_with_prompt(
            prompt_prefix=BRIEF_PROMPT,
            context_path=context_path,
            env_file=env_file,
            model_override=model_override,
            max_tokens=2048,
        )
        target = output_dir / "weekly-brief-raw.json"
        label = "weekly-brief"
    else:
        raise LLMError(f"Unknown Phase 4 subtask: {kind}")

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
