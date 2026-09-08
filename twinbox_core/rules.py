"""Pack routing conditions: hard skip_llm + three-band cosine."""

from __future__ import annotations

import re
from typing import Any

from .embeddings import cosine, embed_texts, load_vector


def hard_match(condition: dict[str, Any], env: dict[str, Any]) -> bool:
    hard = condition.get("hard") if isinstance(condition.get("hard"), dict) else condition
    if not isinstance(hard, dict):
        return False
    sender = str(env.get("from_addr", "") or "")
    folder = str(env.get("folder", "") or "")
    role = str(env.get("recipient_role", "") or "")
    subject = str(env.get("subject", "") or "")
    if "from_addr_regex" in hard:
        if not re.search(str(hard["from_addr_regex"]), sender, re.I):
            return False
    if "folder" in hard and str(hard["folder"]) != folder:
        return False
    if "recipient_role" in hard and str(hard["recipient_role"]) != role:
        return False
    if "subject_regex" in hard:
        if not re.search(str(hard["subject_regex"]), subject, re.I):
            return False
    interesting = {"from_addr_regex", "folder", "recipient_role", "subject_regex"}
    return any(k in hard for k in interesting)


def skip_llm_envelopes(pack: dict[str, Any] | None, envelopes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not pack:
        return []
    skipped: list[dict[str, Any]] = []
    for cond in pack.get("routing_conditions", []) or []:
        if not isinstance(cond, dict) or not cond.get("skip_llm"):
            continue
        for env in envelopes:
            if hard_match(cond, env):
                skipped.append(env)
    return skipped


def semantic_band(
    pack: dict[str, Any] | None,
    env: dict[str, Any],
    state_root,
    llm_probe=None,
) -> str:
    """Return hit / miss / llm / skip."""
    if not pack:
        return "skip"
    hints = pack.get("attention_hints") or []
    if not hints:
        return "skip"
    folder = str(env.get("folder", "INBOX") or "INBOX")
    uid = str(env.get("id", "") or "")
    vec = load_vector(state_root, folder, uid)
    if not vec:
        return "llm"
    best = 0.0
    high = 0.82
    low = 0.55
    utterances: list[str] = []
    for hint in hints:
        if not isinstance(hint, dict):
            continue
        high = float(hint.get("threshold_high", high))
        low = float(hint.get("threshold_low", low))
        utterances.extend(str(u) for u in hint.get("utterances", []) if str(u).strip())
    try:
        hvecs = embed_texts(utterances[:8]) if utterances else []
    except Exception:
        return "llm"
    for hv in hvecs:
        best = max(best, cosine(vec, hv))
    if best >= high:
        return "hit"
    if best <= low:
        return "miss"
    if llm_probe is not None:
        return "llm" if llm_probe(env) else "miss"
    return "llm"
