"""Phase 1 intent classification core."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from twinbox_core.llm import LLMError, call_llm, clean_json_text, resolve_backend


SYSTEM_PROMPT = """You are an email intent classifier for a business mailbox.

Classify each email into exactly ONE intent from this taxonomy:
- support: customer support, bug reports, tickets, troubleshooting
- finance: invoices, payments, budgets, contracts, reimbursements
- recruiting: job postings, interviews, candidates, offers, HR
- scheduling: meetings, calendar invites, time coordination
- receipt: delivery confirmations, read receipts, acknowledgments
- newsletter: newsletters, digests, event announcements, marketing
- internal_update: company notices, policy updates, compliance, training
- collaboration: project discussions, code reviews, shared docs, teamwork
- escalation: urgent requests, complaints, SLA breaches
- human: personal/social messages that need human judgment

For each email, provide:
1. intent: one of the above categories
2. confidence: 0.0-1.0 (how certain you are)
3. evidence: 1-3 short reasons supporting your classification

Respond with valid JSON only. No markdown fences."""


@dataclass(frozen=True)
class IntentRunConfig:
    context_path: Path
    output_dir: Path
    batch_size: int
    dry_run: bool
    env_file: Path | None
    model_override: str | None


def generated_at() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def build_batch_prompt(batch: list[dict[str, object]], body_map: dict[str, dict[str, object]]) -> str:
    items: list[str] = []
    for index, envelope in enumerate(batch):
        entry = body_map.get(str(envelope.get("id")), {})
        body = str(entry.get("body", "")) if isinstance(entry, dict) else ""
        body_snippet = body[:500] if body else "(no body sampled)"
        items.append(
            "\n".join(
                [
                    f"[{index}] id={envelope.get('id')} folder={envelope.get('folder')}",
                    f"  from: {envelope.get('from_name', '')} <{envelope.get('from_addr', '')}>",
                    f"  subject: {envelope.get('subject', '')}",
                    f"  date: {envelope.get('date', '')}",
                    f"  has_attachment: {envelope.get('has_attachment', False)}",
                    f"  body_preview: {body_snippet}",
                ]
            )
        )

    return (
        f'Classify these {len(batch)} emails. Return a JSON array where each element has: '
        '{"id": "...", "intent": "...", "confidence": 0.X, "evidence": ["...", "..."]}\n\n'
        + "\n\n".join(items)
    )


def _fallback_classification(envelope: dict[str, object], reason: str) -> dict[str, object]:
    return {
        "id": str(envelope.get("id", "")),
        "intent": "human",
        "confidence": 0.0,
        "evidence": [reason],
    }


def _normalize_results(batch: list[dict[str, object]], cleaned: str) -> list[dict[str, object]]:
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Invalid JSON array after cleanup: {exc.msg}") from exc

    if not isinstance(parsed, list):
        raise LLMError("Expected a JSON array from Phase 1 classifier response")

    by_id = {str(item.get("id", "")): item for item in parsed if isinstance(item, dict)}
    normalized: list[dict[str, object]] = []
    for envelope in batch:
        envelope_id = str(envelope.get("id", ""))
        result = by_id.get(envelope_id)
        if result is None:
            normalized.append(_fallback_classification(envelope, "LLM omitted item from batch"))
            continue
        normalized.append(
            {
                "id": envelope_id,
                "intent": str(result.get("intent", "human")),
                "confidence": float(result.get("confidence", 0.5) or 0.0),
                "evidence": [
                    str(item) for item in result.get("evidence", []) if isinstance(item, (str, int, float))
                ],
            }
        )
    return normalized


def build_report(output: dict[str, object]) -> str:
    classifications = list(output.get("classifications", []))
    distribution = dict(output.get("distribution", {}))
    sorted_distribution = sorted(distribution.items(), key=lambda item: item[1], reverse=True)
    total = len(classifications)
    high_conf = sum(1 for item in classifications if float(item.get("confidence", 0.0)) >= 0.8)
    low_conf = sum(1 for item in classifications if float(item.get("confidence", 0.0)) < 0.5)

    lines = [
        "# Phase 1 Intent Classification Report",
        "",
        f"Generated: {output['generated_at']}",
        f"Model: {output['model']}",
        f"Total classified: {total}",
        "",
        "## Distribution",
        "",
        "| Intent | Count | Ratio |",
        "|--------|-------|-------|",
    ]
    for intent, count in sorted_distribution:
        ratio = 0.0 if total == 0 else count / total * 100
        lines.append(f"| {intent} | {count} | {ratio:.1f}% |")
    lines.extend(
        [
            "",
            "## Confidence",
            "",
            f"- High confidence (>=0.8): {high_conf} ({0.0 if total == 0 else high_conf / total * 100:.1f}%)",
            f"- Low confidence (<0.5): {low_conf} ({0.0 if total == 0 else low_conf / total * 100:.1f}%)",
            "",
            "## Notes",
            "",
            "- Each classification includes an evidence chain for auditability",
            "- Low-confidence items should be reviewed manually before downstream use",
            "- Distribution informs Phase 2 profile inference priorities",
            "",
        ]
    )
    return "\n".join(lines)


def run_phase1_intent(config: IntentRunConfig) -> dict[str, object]:
    context = json.loads(config.context_path.read_text(encoding="utf-8"))
    envelopes = context.get("envelopes", [])
    if not isinstance(envelopes, list):
        raise LLMError("phase1-context.json is missing envelopes[]")

    body_map = context.get("sampled_bodies", {})
    if not isinstance(body_map, dict):
        body_map = {}

    config.output_dir.mkdir(parents=True, exist_ok=True)

    model_name = config.model_override
    if not config.dry_run:
        backend = resolve_backend(env_file=config.env_file)
        if model_name is None:
            model_name = backend.model
        print(f"LLM backend: {backend.backend} ({backend.model})")
    elif model_name is None:
        model_name = "dry-run"

    batches = [envelopes[index : index + config.batch_size] for index in range(0, len(envelopes), config.batch_size)]
    print(f"Processing {len(envelopes)} envelopes in {len(batches)} batch(es)...")

    all_classifications: list[dict[str, object]] = []

    for batch_index, batch in enumerate(batches, start=1):
        prompt = build_batch_prompt(batch, body_map)

        if config.dry_run:
            print(f"\n--- Batch {batch_index}/{len(batches)} ({len(batch)} items) ---")
            preview = prompt[:500]
            suffix = "..." if len(prompt) > 500 else ""
            print(f"{preview}{suffix}\n")
            all_classifications.extend(
                _fallback_classification(envelope, "dry-run placeholder") for envelope in batch
            )
            continue

        print(f"Batch {batch_index}/{len(batches)} ({len(batch)} items)...")
        try:
            raw = call_llm(
                prompt,
                max_tokens=4096,
                system_prompt=SYSTEM_PROMPT,
                env_file=config.env_file,
                model_override=config.model_override,
            )
            cleaned = clean_json_text(raw)
            normalized = _normalize_results(batch, cleaned)
            all_classifications.extend(normalized)
            print(f"  Classified {len(normalized)} items")
        except (LLMError, ValueError) as exc:
            print(f"  Error: {exc}")
            all_classifications.extend(_fallback_classification(envelope, f"API error: {exc}") for envelope in batch)

        if batch_index < len(batches):
            time.sleep(0.5)

    distribution: dict[str, int] = {}
    for classification in all_classifications:
        intent = str(classification.get("intent", "human"))
        distribution[intent] = distribution.get(intent, 0) + 1

    output = {
        "generated_at": generated_at(),
        "model": model_name,
        "dry_run": config.dry_run,
        "stats": {
            "total_classified": len(all_classifications),
            "total_envelopes": len(envelopes),
            "batches": len(batches),
        },
        "distribution": distribution,
        "classifications": all_classifications,
    }

    output_path = config.output_dir / "intent-classification.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nClassification written: {output_path}")

    report_path = config.output_dir / "intent-report.md"
    report_path.write_text(build_report(output), encoding="utf-8")
    print(f"Report written: {report_path}")
    return output


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--model")
    parser.add_argument("--env-file")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        run_phase1_intent(
            IntentRunConfig(
                context_path=Path(args.context).expanduser(),
                output_dir=Path(args.output_dir).expanduser(),
                batch_size=args.batch_size,
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
