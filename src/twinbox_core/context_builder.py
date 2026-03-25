"""Shared Phase 2/3 loading context builders."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .mailbox import load_env_file


class ContextBuilderError(RuntimeError):
    """Raised when a phase context pack cannot be built."""


@dataclass(frozen=True)
class Phase1Data:
    census: dict[str, object]
    contacts: dict[str, object]
    bodies: list[dict[str, object]]
    envelopes: list[dict[str, object]]
    intents: list[dict[str, object]]


def _read_text_if_exists(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_json_if_exists(path: Path, default: object) -> object:
    if not path.is_file():
        return default
    return _load_json(path)


def _resolve_owner_addr(state_root: Path) -> str:
    owner_addr = str(os.environ.get("MAIL_ADDRESS", "") or "").strip().lower()
    if owner_addr:
        return owner_addr
    return str(load_env_file(state_root / ".env").get("MAIL_ADDRESS", "") or "").strip().lower()


def _parse_yaml_simple_items(text: str) -> list[str]:
    if not text or text in {"facts: []", "habits: []"}:
        return []

    items: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        if re.match(r"^\s+-\s+id:", raw_line):
            if current:
                items.append("\n".join(current))
            current = [re.sub(r"^\s+-\s+", "", raw_line)]
            continue
        if current and re.match(r"^\s{4,}\S", raw_line):
            current.append(raw_line.strip())
    if current:
        items.append("\n".join(current))
    return items


def _top_n(counts: dict[str, int], limit: int = 10) -> list[dict[str, object]]:
    return [
        {"key": key, "count": count}
        for key, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def _normalize_thread(subject: object, *, strip_date_suffix: bool = False) -> str:
    value = str(subject or "").lower()
    value = re.sub(r"^(\s*(re|fw|fwd|回复|转发|答复)\s*[:：])+\s*", "", value, flags=re.IGNORECASE)
    if strip_date_suffix:
        value = re.sub(r"[-_ ]?(20\d{6}|\d{8})$", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or "(no-subject)"


def _extract_tokens(text: object) -> list[str]:
    stop_words = {
        "re",
        "fw",
        "fwd",
        "回复",
        "转发",
        "关于",
        "通知",
        "请",
        "公司",
        "the",
        "and",
        "for",
        "with",
        "to",
        "of",
        "in",
    }
    tokens = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", str(text or ""))
    return [token.lower() for token in tokens if token.lower() not in stop_words]


def _sender_addr(envelope: dict[str, object]) -> str:
    sender = envelope.get("from", {})
    if isinstance(sender, dict) and sender.get("addr") is not None:
        return str(sender.get("addr", "")).lower()
    return str(envelope.get("from_addr", "")).lower()


def _sender_name(envelope: dict[str, object]) -> str:
    sender = envelope.get("from", {})
    if isinstance(sender, dict) and sender.get("name") is not None:
        return str(sender.get("name", "")).strip()
    return str(envelope.get("from_name", "")).strip()


def _sender_domain(envelope: dict[str, object]) -> str:
    addr = _sender_addr(envelope)
    if "@" not in addr:
        return "unknown"
    return addr.rsplit("@", 1)[1]


def _extract_header_addrs(header_value: str) -> list[str]:
    """Extract lowercase email addresses from a MIME header value like 'Name <addr>, addr2'."""
    addrs = re.findall(r"<([^>]+)>|([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})", header_value)
    return [
        (a or b).lower().strip()
        for a, b in addrs
        if (a or b).strip()
    ]


def _parse_mime_recipient_role(body_text: str, owner_addr: str) -> str:
    """Parse To:/Cc: from MIME headers at top of body_text.

    Returns:
    - "to": owner explicitly in To
    - "cc": owner explicitly in Cc
    - "group": recipient headers exist but owner is absent from both To and Cc
    - "unknown": recipient headers missing or cannot be parsed
    """
    if not owner_addr or not body_text:
        return "unknown"
    owner = owner_addr.lower().strip()
    to_addrs: list[str] = []
    cc_addrs: list[str] = []
    saw_recipient_headers = False
    current_header = ""
    for line in body_text.splitlines():
        if not line.strip():
            break  # end of headers
        if line[0] in (" ", "\t") and current_header:
            # header continuation
            if current_header == "to":
                to_addrs.extend(_extract_header_addrs(line))
            elif current_header == "cc":
                cc_addrs.extend(_extract_header_addrs(line))
        elif ":" in line:
            key, _, val = line.partition(":")
            current_header = key.strip().lower()
            if current_header == "to":
                saw_recipient_headers = True
                to_addrs.extend(_extract_header_addrs(val))
            elif current_header == "cc":
                saw_recipient_headers = True
                cc_addrs.extend(_extract_header_addrs(val))
    if owner in to_addrs:
        return "to"
    if owner in cc_addrs:
        return "cc"
    if saw_recipient_headers:
        return "group"
    return "unknown"


def _aggregate_thread_recipient_role(rows: list[dict[str, object]]) -> str:
    """Collapse message-level recipient roles into a stable thread-level role."""
    classified_roles = {
        str(row.get("recipient_role", "") or "")
        for row in rows
        if str(row.get("recipient_role", "") or "") in {"to", "cc", "group"}
    }
    if "to" in classified_roles:
        return "direct"
    if classified_roles == {"cc"}:
        return "cc_only"
    if classified_roles == {"group"}:
        return "group_only"
    if classified_roles == {"cc", "group"}:
        return "indirect"
    return "unknown"


def _normalize_envelope(
    envelope: dict[str, object],
    owner_addr: str = "",
    recipient_role: str = "unknown",
) -> dict[str, object]:
    sender = envelope.get("from", {})
    if not isinstance(sender, dict):
        sender = {}

    # If raw envelope has to.addr, use it directly (legacy path)
    if not recipient_role or recipient_role == "unknown":
        to_field = envelope.get("to", {})
        if isinstance(to_field, dict):
            to_addr = str(to_field.get("addr", "") or "").lower()
            if owner_addr and to_addr:
                recipient_role = "to" if to_addr == owner_addr.lower() else "unknown"

    return {
        "id": str(envelope.get("id", "")),
        "folder": envelope.get("folder", "INBOX") or "INBOX",
        "subject": envelope.get("subject", "") or "",
        "date": envelope.get("date", "") or "",
        "has_attachment": bool(envelope.get("has_attachment", False)),
        "from": {
            "addr": sender.get("addr", envelope.get("from_addr", "")) or "",
            "name": sender.get("name", envelope.get("from_name", "")) or "",
        },
        "recipient_role": recipient_role,
    }


def _load_intents_from_dir(path: Path) -> list[dict[str, object]]:
    if not path.is_dir():
        return []

    items: list[dict[str, object]] = []
    for child in sorted(path.iterdir()):
        if child.suffix != ".json":
            continue
        parsed = _load_json(child)
        if isinstance(parsed, list):
            items.extend(item for item in parsed if isinstance(item, dict))
    return items


def _derive_legacy_artifacts(
    *,
    envelopes: list[dict[str, object]],
    intents: list[dict[str, object]],
    owner_domain: str,
    folders_scanned: list[object],
    lookback_days: object,
) -> tuple[dict[str, object], dict[str, object]]:
    by_domain: dict[str, int] = {}
    by_sender: dict[str, int] = {}
    by_keyword: dict[str, int] = {}
    by_intent: dict[str, int] = {}
    by_internal_external = {"internal": 0, "external": 0, "unknown": 0}
    thread_counts: dict[str, int] = {}
    with_attachment = 0

    intent_by_id = {str(intent.get("id", "")): intent for intent in intents}

    for envelope in envelopes:
        domain = _sender_domain(envelope)
        sender = _sender_addr(envelope) or _sender_name(envelope) or "unknown"
        intent = str(intent_by_id.get(str(envelope.get("id", "")), {}).get("intent", "unknown"))

        by_domain[domain] = by_domain.get(domain, 0) + 1
        by_sender[sender] = by_sender.get(sender, 0) + 1
        by_intent[intent] = by_intent.get(intent, 0) + 1

        thread_key = _normalize_thread(envelope.get("subject", ""))
        thread_counts[thread_key] = thread_counts.get(thread_key, 0) + 1

        for token in _extract_tokens(envelope.get("subject", "")):
            by_keyword[token] = by_keyword.get(token, 0) + 1

        if bool(envelope.get("has_attachment", False)):
            with_attachment += 1

        if domain == "unknown":
            by_internal_external["unknown"] += 1
        elif owner_domain and domain == owner_domain:
            by_internal_external["internal"] += 1
        else:
            by_internal_external["external"] += 1

    total = len(envelopes)
    threads_top = _top_n(thread_counts, 15)
    census = {
        "generated_at": None,
        "scope": {
            "folders_scanned": folders_scanned,
            "lookback_days": lookback_days,
            "total_envelopes": total,
            "sampled_bodies": 0,
        },
        "distributions": {"internal_external": by_internal_external},
        "metrics": {
            "attachment_ratio": 0 if total == 0 else round(with_attachment / total, 4),
        },
        "threads": {
            "high_frequency": threads_top[:10],
            "long_threads": [thread for thread in threads_top if int(thread["count"]) >= 3],
        },
        "top": {
            "intents": _top_n(by_intent, 10),
            "domains": _top_n(by_domain, 10),
            "contacts": _top_n(by_sender, 15),
            "keywords": _top_n(by_keyword, 15),
        },
    }
    contacts = {
        "top_contacts": _top_n(by_sender, 30),
        "top_domains": _top_n(by_domain, 30),
    }
    return census, contacts


def _load_phase1_data(state_root: Path) -> Phase1Data:
    phase1_dir = state_root / "runtime/validation/phase-1"
    census_path = phase1_dir / "mailbox-census.json"
    contact_path = phase1_dir / "contact-distribution.json"
    bodies_path = phase1_dir / "raw/sample-bodies.json"
    envelopes_path = phase1_dir / "raw/envelopes-merged.json"
    intent_dir = phase1_dir / "intent-results"
    phase1_context_path = state_root / "runtime/context/phase1-context.json"
    intent_classification_path = phase1_dir / "intent-classification.json"

    if not phase1_context_path.is_file() or not intent_classification_path.is_file():
        raise ContextBuilderError(
            "Missing Phase 1 outputs.\nRun Phase 1 first: bash scripts/phase1_loading.sh && bash scripts/phase1_thinking.sh"
        )

    owner_addr = _resolve_owner_addr(state_root)

    if census_path.is_file() and bodies_path.is_file() and envelopes_path.is_file():
        census = _load_json(census_path)
        contacts = _load_json_if_exists(contact_path, {})
        bodies = _load_json(bodies_path)
        envelopes_raw = _load_json(envelopes_path)
        intents = _load_intents_from_dir(intent_dir)
        if not isinstance(census, dict) or not isinstance(contacts, dict) or not isinstance(bodies, list) or not isinstance(envelopes_raw, list):
            raise ContextBuilderError("Legacy Phase 1 artifacts have unexpected structure")
        # Build body lookup for recipient_role parsing (keyed by message id)
        body_by_id: dict[str, str] = {}
        for b in bodies:
            if isinstance(b, dict):
                bid = str(b.get("id", ""))
                body_by_id[bid] = str(b.get("body", "") or "")
        envelopes = [
            _normalize_envelope(
                envelope,
                owner_addr=owner_addr,
                recipient_role=_parse_mime_recipient_role(
                    body_by_id.get(str(envelope.get("id", "")), ""), owner_addr
                ),
            )
            for envelope in envelopes_raw
            if isinstance(envelope, dict)
        ]
        return Phase1Data(census=census, contacts=contacts, bodies=[row for row in bodies if isinstance(row, dict)], envelopes=envelopes, intents=intents)

    phase1_context = _load_json(phase1_context_path)
    intent_classification = _load_json(intent_classification_path)
    if not isinstance(phase1_context, dict) or not isinstance(intent_classification, dict):
        raise ContextBuilderError("Phase 1 context artifacts have unexpected structure")

    sampled_bodies = phase1_context.get("sampled_bodies", {})
    if not isinstance(sampled_bodies, dict):
        sampled_bodies = {}
    envelopes = [
        _normalize_envelope(
            envelope,
            owner_addr=owner_addr,
            recipient_role=_parse_mime_recipient_role(
                str((sampled_bodies.get(str(envelope.get("id", ""))) or {}).get("body", "") or ""),
                owner_addr,
            ),
        )
        for envelope in phase1_context.get("envelopes", [])
        if isinstance(envelope, dict)
    ]
    envelope_by_id = {str(envelope.get("id", "")): envelope for envelope in envelopes}

    bodies = [
        {
            "id": body_id,
            "folder": envelope_by_id.get(str(body_id), {}).get("folder", ""),
            "subject": row.get("subject", "") if isinstance(row, dict) else "",
            "body": row.get("body", "") if isinstance(row, dict) else "",
        }
        for body_id, row in sampled_bodies.items()
    ]
    intents = [
        item for item in intent_classification.get("classifications", []) if isinstance(item, dict)
    ]
    census, contacts = _derive_legacy_artifacts(
        envelopes=envelopes,
        intents=intents,
        owner_domain=str(phase1_context.get("owner_domain", "")).lower(),
        folders_scanned=list(phase1_context.get("stats", {}).get("folders_scanned", []))
        if isinstance(phase1_context.get("stats", {}), dict)
        else [],
        lookback_days=phase1_context.get("lookback_days"),
    )
    return Phase1Data(census=census, contacts=contacts, bodies=bodies, envelopes=envelopes, intents=intents)


def _build_human_context(state_root: Path) -> dict[str, object]:
    runtime_context = state_root / "runtime/context"
    facts_raw = _read_text_if_exists(runtime_context / "manual-facts.yaml")
    habits_raw = _read_text_if_exists(runtime_context / "manual-habits.yaml")
    calibration_raw = _read_text_if_exists(runtime_context / "instance-calibration-notes.md")
    facts_items = _parse_yaml_simple_items(facts_raw)
    habits_items = _parse_yaml_simple_items(habits_raw)

    return {
        "facts_raw": facts_raw,
        "habits_raw": habits_raw,
        "calibration_raw": calibration_raw,
        "facts_items": facts_items,
        "habits_items": habits_items,
        "has_facts": len(facts_items) > 0,
        "has_habits": len(habits_items) > 0,
        "has_calibration": len(calibration_raw) > 50,
    }


def _internal_external(census: dict[str, object]) -> dict[str, int]:
    distributions = census.get("distributions", {})
    if not isinstance(distributions, dict):
        return {"internal": 0, "external": 0, "unknown": 0}
    internal_external = distributions.get("internal_external") or distributions.get("byInternalExternal")
    if not isinstance(internal_external, dict):
        return {"internal": 0, "external": 0, "unknown": 0}
    return {
        "internal": int(internal_external.get("internal", 0) or 0),
        "external": int(internal_external.get("external", 0) or 0),
        "unknown": int(internal_external.get("unknown", 0) or 0),
    }


def run_phase2_loading(state_root: Path) -> dict[str, object]:
    phase2_dir = state_root / "runtime/validation/phase-2"
    doc_dir = state_root / "docs/validation"
    diagram_dir = doc_dir / "diagrams"
    phase2_dir.mkdir(parents=True, exist_ok=True)
    doc_dir.mkdir(parents=True, exist_ok=True)
    diagram_dir.mkdir(parents=True, exist_ok=True)

    data = _load_phase1_data(state_root)
    human_context = _build_human_context(state_root)
    envelope_by_id = {str(envelope.get("id", "")): envelope for envelope in data.envelopes}
    intent_by_idx = {index: intent for index, intent in enumerate(data.intents)}
    intent_by_id = {
        str(intent.get("id", "")): intent
        for intent in data.intents
        if intent.get("id") is not None and intent.get("id") != ""
    }

    enriched_samples: list[dict[str, object]] = []
    for index, body_row in enumerate(data.bodies):
        body_id = str(body_row.get("id", ""))
        envelope = envelope_by_id.get(body_id, {})
        intent = intent_by_id.get(body_id, intent_by_idx.get(index, {}))
        if not isinstance(intent, dict):
            intent = {}
        enriched_samples.append(
            {
                "id": body_row.get("id", ""),
                "subject": envelope.get("subject", body_row.get("subject", "")),
                "from": _sender_addr(envelope),
                "from_name": _sender_name(envelope),
                "date": envelope.get("date", ""),
                "folder": envelope.get("folder", body_row.get("folder", "")),
                "intent": intent.get("intent", "unknown"),
                "intent_confidence": intent.get("confidence", 0),
                "intent_evidence": intent.get("evidence", ""),
                "body_excerpt": str(body_row.get("body", ""))[:600],
            }
        )

    context = {
        "mailbox_summary": {
            "total_envelopes": data.census.get("scope", {}).get("total_envelopes", 0)
            if isinstance(data.census.get("scope", {}), dict)
            else 0,
            "folders": data.census.get("scope", {}).get("folders_scanned", [])
            if isinstance(data.census.get("scope", {}), dict)
            else [],
            "internal_external": _internal_external(data.census),
            "attachment_ratio": data.census.get("metrics", {}).get("attachment_ratio", 0)
            if isinstance(data.census.get("metrics", {}), dict)
            else 0,
        },
        "intent_distribution": data.census.get("top", {}).get("intents", [])
        if isinstance(data.census.get("top", {}), dict)
        else [],
        "top_domains": data.census.get("top", {}).get("domains", [])
        if isinstance(data.census.get("top", {}), dict)
        else [],
        "top_contacts": (
            data.contacts.get("top_contacts")
            if isinstance(data.contacts, dict) and "top_contacts" in data.contacts
            else data.census.get("top", {}).get("contacts", [])
            if isinstance(data.census.get("top", {}), dict)
            else []
        )[:15],
        "top_keywords": data.census.get("top", {}).get("keywords", [])
        if isinstance(data.census.get("top", {}), dict)
        else [],
        "high_frequency_threads": data.census.get("threads", {}).get("high_frequency", [])
        if isinstance(data.census.get("threads", {}), dict)
        else [],
        "long_threads": data.census.get("threads", {}).get("long_threads", [])
        if isinstance(data.census.get("threads", {}), dict)
        else [],
        "enriched_samples": enriched_samples,
        "human_context": {
            "has_facts": human_context["has_facts"],
            "has_habits": human_context["has_habits"],
            "has_calibration": human_context["has_calibration"],
            "manual_facts_raw": human_context["facts_raw"] if human_context["has_facts"] else None,
            "manual_habits_raw": human_context["habits_raw"] if human_context["has_habits"] else None,
            "calibration_notes": human_context["calibration_raw"][:2000]
            if human_context["has_calibration"]
            else None,
        },
    }

    output_path = phase2_dir / "context-pack.json"
    output_path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    total_envelopes = context["mailbox_summary"]["total_envelopes"]
    print(
        f"Context pack: {len(enriched_samples)} enriched samples, {total_envelopes} total envelopes"
    )
    print(
        "  human_context: "
        f"facts={len(human_context['facts_items'])} "
        f"habits={len(human_context['habits_items'])} "
        f"calibration={'yes' if human_context['has_calibration'] else 'no'}"
    )
    print(f"  -> {output_path}")
    return context


def run_phase3_loading(state_root: Path) -> dict[str, object]:
    phase3_dir = state_root / "runtime/validation/phase-3"
    doc_dir = state_root / "docs/validation"
    diagram_dir = doc_dir / "diagrams"
    phase2_dir = state_root / "runtime/validation/phase-2"
    phase3_dir.mkdir(parents=True, exist_ok=True)
    doc_dir.mkdir(parents=True, exist_ok=True)
    diagram_dir.mkdir(parents=True, exist_ok=True)

    data = _load_phase1_data(state_root)
    human_context = _build_human_context(state_root)
    envelope_by_id = {str(envelope.get("id", "")): envelope for envelope in data.envelopes}
    intent_by_idx = {index: intent for index, intent in enumerate(data.intents)}
    intent_by_id = {
        str(intent.get("id", "")): intent
        for intent in data.intents
        if intent.get("id") is not None and intent.get("id") != ""
    }

    thread_map: dict[str, list[dict[str, object]]] = {}
    for envelope in data.envelopes:
        key = _normalize_thread(envelope.get("subject", ""), strip_date_suffix=True)
        thread_map.setdefault(key, []).append(envelope)
    for rows in thread_map.values():
        rows.sort(key=lambda row: str(row.get("date", "")), reverse=True)

    thread_list = sorted(
        (
            {
                "key": key,
                "count": len(rows),
                "latest_date": rows[0].get("date", "") if rows else "",
            }
            for key, rows in thread_map.items()
        ),
        key=lambda item: item["count"],
        reverse=True,
    )

    body_by_id = {str(body.get("id", "")): body for body in data.bodies}
    body_index_by_id = {str(body.get("id", "")): index for index, body in enumerate(data.bodies)}
    top_threads: list[dict[str, object]] = []
    for thread in thread_list[:20]:
        rows = thread_map.get(str(thread["key"]), [])
        latest = rows[0] if rows else {}
        latest_id = str(latest.get("id", ""))
        body_entry = body_by_id.get(latest_id, {})
        body_index = body_index_by_id.get(latest_id)
        intent_entry = intent_by_id.get(latest_id)
        if intent_entry is None and body_index is not None:
            intent_entry = intent_by_idx.get(body_index)
        if intent_entry is None:
            intent_entry = {}

        participants: list[str] = []
        for row in rows:
            addr = _sender_addr(row)
            if addr and addr not in participants:
                participants.append(addr)

        if len(rows) > 1:
            date_range = f"{rows[-1].get('date', '')} ~ {rows[0].get('date', '')}"
        else:
            date_range = latest.get("date", "")

        thread_recipient_role = _aggregate_thread_recipient_role(rows)

        top_threads.append(
            {
                "thread_key": thread["key"],
                "count": thread["count"],
                "latest_date": thread["latest_date"],
                "latest_subject": latest.get("subject", ""),
                "latest_from": _sender_addr(latest),
                "folder": latest.get("folder", ""),
                "intent": intent_entry.get("intent", "unknown"),
                "intent_confidence": intent_entry.get("confidence", 0),
                "body_excerpt": str(body_entry.get("body", ""))[:500],
                "participants": participants[:5],
                "date_range": date_range,
                "recipient_role": thread_recipient_role,
            }
        )

    persona_raw = _read_text_if_exists(phase2_dir / "persona-hypotheses.yaml")
    business_raw = _read_text_if_exists(phase2_dir / "business-hypotheses.yaml")

    context = {
        "mailbox_summary": {
            "total_envelopes": data.census.get("scope", {}).get("total_envelopes", 0)
            if isinstance(data.census.get("scope", {}), dict)
            else 0,
            "total_threads": len(thread_list),
            "folders": data.census.get("scope", {}).get("folders_scanned", [])
            if isinstance(data.census.get("scope", {}), dict)
            else [],
            "internal_external": _internal_external(data.census),
        },
        "intent_distribution": data.census.get("top", {}).get("intents", [])
        if isinstance(data.census.get("top", {}), dict)
        else [],
        "persona_summary": persona_raw[:1500] or None,
        "business_summary": business_raw[:1500] or None,
        "top_threads": top_threads,
        "human_context": {
            "has_facts": human_context["has_facts"],
            "has_habits": human_context["has_habits"],
            "has_calibration": human_context["has_calibration"],
            "manual_facts_raw": human_context["facts_raw"] if human_context["has_facts"] else None,
            "manual_habits_raw": human_context["habits_raw"] if human_context["has_habits"] else None,
            "calibration_notes": human_context["calibration_raw"][:2000]
            if human_context["has_calibration"]
            else None,
        },
    }

    output_path = phase3_dir / "context-pack.json"
    output_path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    total_envelopes = context["mailbox_summary"]["total_envelopes"]
    print(f"Context pack: {len(top_threads)} top threads, {total_envelopes} total envelopes")
    print(
        "  human_context: "
        f"facts={'yes' if human_context['has_facts'] else 'no'} "
        f"habits={'yes' if human_context['has_habits'] else 'no'} "
        f"calibration={'yes' if human_context['has_calibration'] else 'no'}"
    )
    print(f"  -> {output_path}")
    return context


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    phase2 = subparsers.add_parser("phase2")
    phase2.add_argument("--state-root", required=True)

    phase3 = subparsers.add_parser("phase3")
    phase3.add_argument("--state-root", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    state_root = Path(args.state_root).expanduser()

    try:
        if args.command == "phase2":
            run_phase2_loading(state_root)
            return 0
        if args.command == "phase3":
            run_phase3_loading(state_root)
            return 0
    except (ContextBuilderError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
