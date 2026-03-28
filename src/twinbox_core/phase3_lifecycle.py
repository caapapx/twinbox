"""Phase 3 lifecycle modeling core."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from twinbox_core.llm import LLMError, call_llm, clean_json_text, resolve_backend
from twinbox_core.prompt_fragments import base_human_context_rules, confidence_calibration_note
from twinbox_core.renderer import render_phase3_outputs


@dataclass(frozen=True)
class Phase3RunConfig:
    context_path: Path
    output_dir: Path
    doc_dir: Path
    diagram_dir: Path
    dry_run: bool
    env_file: Path | None
    model_override: str | None


def build_prompt(context_text: str) -> tuple[str, str]:
    system = """You are an enterprise email workflow analyst. Based on the mailbox data, persona hypotheses, and thread summaries below, build a thread-level lifecycle model.

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
5. """ + base_human_context_rules() + """
6. Output ONLY the JSON object. No markdown, no explanation.
""" + confidence_calibration_note()
    user = "## Mailbox data:\n" + context_text
    return system, user


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


def run_phase3_lifecycle(config: Phase3RunConfig) -> dict[str, object]:
    context = _load_object(config.context_path)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.doc_dir.mkdir(parents=True, exist_ok=True)
    config.diagram_dir.mkdir(parents=True, exist_ok=True)

    system, user = build_prompt(config.context_path.read_text(encoding="utf-8"))
    if config.dry_run:
        print(f"=== SYSTEM length: {len(system)} chars ===")
        print(f"=== USER length: {len(user)} chars ===")
        print("=== DRY RUN ===")
        return {"dry_run": True}

    backend = resolve_backend(env_file=config.env_file)
    model_name = config.model_override or backend.model
    print(f"LLM backend: {backend.backend} ({backend.model})")
    print("Calling LLM for lifecycle modeling...")
    response = _parse_response(
        call_llm(
            user,
            max_tokens=8192,
            system_prompt=system,
            env_file=config.env_file,
            model_override=config.model_override,
        )
    )

    print("LLM response saved.")
    print("Generating Phase 3 outputs...")
    render_phase3_outputs(
        output_dir=config.output_dir,
        doc_dir=config.doc_dir,
        diagram_dir=config.diagram_dir,
        response=response,
        model_name=model_name,
    )
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
