"""Phase 2 persona and business inference core."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from twinbox_core.artifacts import generated_at, write_lines, yaml_string
from twinbox_core.llm import LLMError, call_llm, clean_json_text, resolve_backend


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


def _build_relationship_map(context: dict[str, object]) -> list[str]:
    contacts = context.get("top_contacts", [])
    domains = context.get("top_domains", [])

    lines = ["graph TD", '  User["Mailbox Owner"]']
    if isinstance(contacts, list):
        for contact in contacts[:8]:
            if not isinstance(contact, dict):
                continue
            key = str(contact.get("key", "unknown"))
            safe = "".join(char if char.isascii() and char.isalnum() else "_" for char in key)
            lines.append(f'  C_{safe}["{key}"]')
            lines.append(f'  User ---|{contact.get("count", 0)}| C_{safe}')
    if isinstance(domains, list):
        for domain in domains[:3]:
            if not isinstance(domain, dict):
                continue
            key = str(domain.get("key", "unknown"))
            safe = "".join(char if char.isascii() and char.isalnum() else "_" for char in key)
            lines.append(f'  D_{safe}["{key}"]')
            lines.append(f"  User --> D_{safe}")
    return lines


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

    llm_response_path = config.output_dir / "llm-response.json"
    llm_response_path.write_text(
        json.dumps(response, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("LLM response saved.")
    print("Generating Phase 2 outputs...")

    persona = response.get("persona_hypotheses", [])
    business = response.get("business_hypotheses", [])
    questions = response.get("confirmation_questions", [])

    persona_lines = [
        f'generated_at: "{generated_at()}"',
        'method: "llm"',
        f'model: "{model_name}"',
        "persona_hypotheses:",
    ]
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
    write_lines(config.output_dir / "persona-hypotheses.yaml", persona_lines)

    business_lines = [
        f'generated_at: "{generated_at()}"',
        'method: "llm"',
        f'model: "{model_name}"',
        "business_hypotheses:",
    ]
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
    write_lines(config.output_dir / "business-hypotheses.yaml", business_lines)

    write_lines(config.diagram_dir / "phase-2-relationship-map.mmd", _build_relationship_map(context))

    mailbox_summary = context.get("mailbox_summary", {})
    internal_external = {}
    if isinstance(mailbox_summary, dict):
        internal_external = mailbox_summary.get("internal_external", {})
    intent_distribution = context.get("intent_distribution", [])
    top_contacts = context.get("top_contacts", [])
    top_domains = context.get("top_domains", [])
    intent_summary = ", ".join(
        f"{item.get('key')}({item.get('count')})"
        for item in intent_distribution
        if isinstance(item, dict)
    )
    contact_summary = ", ".join(
        f"{item.get('key')}({item.get('count')})" for item in top_contacts[:5] if isinstance(item, dict)
    )
    domain_summary = ", ".join(
        f"{item.get('key')}({item.get('count')})" for item in top_domains[:3] if isinstance(item, dict)
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
    write_lines(config.doc_dir / "phase-2-report.md", report_lines)
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
