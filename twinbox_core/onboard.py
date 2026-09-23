"""Minimal onboarding questionnaire → user Semantic Pack."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .pack import validate_pack

QUESTIONS = [
    {"id": "approvals", "prompt": "日常需要你审批或回复的是什么？"},
    {"id": "watch", "prompt": "特别关注谁或什么主题？"},
    {"id": "extra", "prompt": "额外留意的方向？"},
    {"id": "broadcast", "prompt": "制度/通告默认进参考类吗？（跳过=是）"},
    {"id": "sensitive", "prompt": "需要单独标记的敏感话题？"},
]

_EMAIL_RE = re.compile(r"<([^<>@\s]+@[^<>@\s]+)>|([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def _split_addresses(value: object) -> list[str]:
    """Extract lowercased addresses from a To-style header value."""
    if not value:
        return []
    found: list[str] = []
    for match in _EMAIL_RE.finditer(str(value)):
        addr = match.group(1) or match.group(2)
        if addr:
            found.append(addr.lower())
    return found


def propose_who_matters(state_root: Path, *, limit: int = 8) -> list[dict[str, Any]]:
    """Propose candidate addresses by counting To on sent headers (no bodies).

    Pure read of ``runtime/context/sent-headers.json``; never touches IMAP.  A
    missing or malformed file yields an empty list.  Ordering is deterministic by
    descending count, then ascending address.
    """
    path = state_root / "runtime" / "context" / "sent-headers.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    headers = data.get("headers") if isinstance(data, dict) else []
    if not isinstance(headers, list):
        return []
    counts: dict[str, int] = {}
    for row in headers:
        if not isinstance(row, dict):
            continue
        for addr in _split_addresses(row.get("to")):
            counts[addr] = counts.get(addr, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"address": addr, "count": n} for addr, n in ranked[: max(1, limit)]]


def _coerce_who_matters(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        return None
    addresses: list[str] = []
    for item in items:
        addresses.extend(_split_addresses(item))
    if not addresses:
        return None
    return addresses


def _coerce_pairwise(value: object) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
    else:
        parsed = value
    if not isinstance(parsed, list):
        return None
    pairs = [p for p in parsed if isinstance(p, dict)]
    return pairs or None


def answers_to_pack(
    answers: dict[str, str],
    *,
    who_matters: object = None,
    pairwise: object = None,
) -> dict[str, Any]:
    hints = []
    for key in ("approvals", "watch", "extra", "sensitive"):
        text = str(answers.get(key, "") or "").strip()
        if text:
            hints.append({"id": key, "utterances": [text], "threshold_high": 0.82, "threshold_low": 0.55})
    broadcast = str(answers.get("broadcast", "") or "").strip()
    classification = {
        "event_types": [{"id": "attention", "when": {}}],
        "defaults": {"broadcast": "reference" if broadcast.lower() in {"", "yes", "y", "是", "跳过"} else "watch"},
    }
    pack = {
        "id": "user",
        "version": "1.0.0",
        "entities": [],
        "relations": [],
        "classification": classification,
        "attention_hints": hints,
        "routing_conditions": [],
        "action_policy": [],
    }
    who = _coerce_who_matters(who_matters if who_matters is not None else answers.get("who_matters"))
    if who is not None:
        pack["who_matters"] = who
    pairs = _coerce_pairwise(pairwise if pairwise is not None else answers.get("pairwise"))
    if pairs is not None:
        pack["pairwise"] = pairs
    return validate_pack(pack)


def save_user_pack(
    state_root: Path,
    answers: dict[str, str],
    *,
    who_matters: object = None,
    pairwise: object = None,
) -> dict[str, Any]:
    pack = answers_to_pack(answers, who_matters=who_matters, pairwise=pairwise)
    path = state_root / "packs" / "user.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True, "path": str(path), "id": pack["id"], "version": pack["version"], "fingerprint": pack["fingerprint"]}
