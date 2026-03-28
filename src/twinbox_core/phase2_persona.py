"""Phase 2 persona and business inference core."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from twinbox_core.llm import LLMError, call_llm, clean_json_text, resolve_backend
from twinbox_core.renderer import render_phase2_outputs


@dataclass(frozen=True)
class Phase2RunConfig:
    context_path: Path
    output_dir: Path
    doc_dir: Path
    diagram_dir: Path
    dry_run: bool
    env_file: Path | None
    model_override: str | None


def build_prompt(context_text: str) -> str:
    return """You are an enterprise email analyst. Based on the mailbox statistics and email samples below, infer the mailbox owner's profile and their company's business profile.

## Your task

Produce a JSON object with exactly this structure:
{
  "persona_hypotheses": [
    {
      "id": "P1",
      "type": "<role | responsibility | collaboration_pattern | communication_style>",
      "hypothesis": "<one sentence in Chinese>",
      "confidence": <0.0-1.0>,
      "evidence": ["<specific data point from the input>", "..."]
    }
  ],
  "business_hypotheses": [
    {
      "id": "B1",
      "hypothesis": "<one sentence in Chinese>",
      "confidence": <0.0-1.0>,
      "evidence": ["<specific data point>", "..."],
      "ai_entry_points": ["<where AI can add value, in Chinese>", "..."]
    }
  ],
  "confirmation_questions": [
    "<question in Chinese, max 7>"
  ]
}

## Rules
1. Generate 3-5 persona hypotheses and 2-4 business hypotheses
2. Confidence must reflect actual certainty — do NOT default to 0.85+
3. Every evidence item must reference a concrete number, sender, thread, or intent from the input
4. Do not invent data not present in the input
5. confirmation_questions: max 7, each should resolve one ambiguity
6. If human_context is provided in the input, use it to refine your hypotheses:
   - Human-provided facts OVERRIDE email-only inference when they conflict
   - Mark evidence source: "mail_evidence" for email data, "user_declared_rule" or "user_confirmed_fact" for human context
   - If human context contradicts email evidence, flag the conflict in the evidence array
   - Periodic tasks from manual_habits should appear in relevant hypotheses
   - If `onboarding_profile_notes` is non-null in human_context, treat it as user-declared role/habits/preferences from Twinbox conversational onboarding; align persona hypotheses and cite "user_confirmed_fact" / onboarding_notes in evidence
7. Output ONLY the JSON object. No markdown fences, no explanation.

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
        raise LLMError("Expected a JSON object from Phase 2 response")
    return parsed


def run_phase2_persona(config: Phase2RunConfig) -> dict[str, object]:
    context = _load_object(config.context_path)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.doc_dir.mkdir(parents=True, exist_ok=True)
    config.diagram_dir.mkdir(parents=True, exist_ok=True)

    prompt = build_prompt(config.context_path.read_text(encoding="utf-8"))
    if config.dry_run:
        print("=== PROMPT (first 200 lines) ===")
        for line in prompt.splitlines()[:200]:
            print(line)
        print("...")
        print("=== DRY RUN, no LLM call ===")
        return {"dry_run": True}

    backend = resolve_backend(env_file=config.env_file)
    model_name = config.model_override or backend.model
    print(f"LLM backend: {backend.backend} ({backend.model})")
    print("Calling LLM for persona + business inference...")
    response = _parse_response(
        call_llm(
            prompt,
            max_tokens=4096,
            env_file=config.env_file,
            model_override=config.model_override,
        )
    )

    print("LLM response saved.")
    print("Generating Phase 2 outputs...")
    render_phase2_outputs(
        output_dir=config.output_dir,
        doc_dir=config.doc_dir,
        diagram_dir=config.diagram_dir,
        context=context,
        response=response,
        model_name=model_name,
    )
    print("Phase 2 outputs generated.")
    print("")
    print("Phase 2 thinking complete.")
    print("Outputs:")
    print(f"  {config.output_dir / 'persona-hypotheses.yaml'}")
    print(f"  {config.output_dir / 'business-hypotheses.yaml'}")
    print(f"  {config.output_dir / 'llm-response.json'}")
    print(f"  {config.doc_dir / 'phase-2-report.md'}")
    print(f"  {config.diagram_dir / 'phase-2-relationship-map.mmd'}")
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
        run_phase2_persona(
            Phase2RunConfig(
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
