"""Candidate thread selection: structure + pack attention_hints cosine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .embeddings import cosine, embed_texts, load_vector, rerank
from .imap_fetch import MAX_THREAD_CANDIDATES, _structure_score, rank_thread_candidates
from .pack import load_active_pack
from .pulse import normalize_thread_key

# Cosine in [0, 1] maps to 0–50 so it can trade with unread(+20)+To(+30).
# Pack threshold_high/low stay on semantic_band, not here.
_SIM_WEIGHT = 50

ScoredCandidate = tuple[float, float, bool, dict[str, Any]]


def _candidate_key(env: dict[str, Any]) -> tuple[str, str]:
    return (
        str(env.get("folder", "INBOX") or "INBOX"),
        str(env.get("id", "") or ""),
    )


def _is_floor(env: dict[str, Any]) -> bool:
    from .imap_fetch import is_unread

    unread = is_unread(env.get("flags") if isinstance(env.get("flags"), list) else [])
    role = str(env.get("recipient_role", "") or "")
    return unread or role in {"to", "direct"}


def _thread_signals(
    envelopes: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, tuple[int, bool]]:
    """Preserve full-thread signals only for shortlisted candidate threads.

    ``rank_thread_candidates`` has already scanned the complete window.  Avoid
    repeating its regex-heavy normalization for unrelated threads while still
    folding older ``Re:/Fw:`` messages into the selected representative.
    """
    target_keys = {normalize_thread_key(env.get("subject")) for env in candidates}
    out: dict[str, tuple[int, bool]] = {}
    for env in envelopes:
        raw_subject = str(env.get("subject", "") or "")
        simple_key = " ".join(raw_subject.lower().split()) or "(no-subject)"
        if simple_key in target_keys:
            thread_key = simple_key
        else:
            stripped = raw_subject.lstrip().lower()
            may_normalize_to_target = (
                stripped.startswith(("re:", "re：", "fw:", "fw：", "fwd:", "fwd：", "回复:", "回复：", "转发:", "转发：", "答复:", "答复："))
                or (len(simple_key) >= 8 and simple_key[-8:].isdigit())
            )
            if not may_normalize_to_target:
                continue
            thread_key = normalize_thread_key(raw_subject)
            if thread_key not in target_keys:
                continue
        score = _structure_score(env)
        floor = _is_floor(env)
        previous = out.get(thread_key)
        if previous is None:
            out[thread_key] = (score, floor)
        else:
            out[thread_key] = (max(previous[0], score), previous[1] or floor)
    return out


def _hybrid_score(structure_score: int, sim: float) -> float:
    return float(structure_score) + round(max(0.0, float(sim)) * _SIM_WEIGHT)


def _apply_recall_floor(
    picked: list[dict[str, Any]],
    scored: list[ScoredCandidate],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Keep unread/To threads from the structural shortlist if cosine would drop them."""
    if limit <= 0:
        return []
    picked_keys = {_candidate_key(env) for env in picked}
    out = list(picked)
    score_of = {
        _candidate_key(env): (score, sim)
        for score, sim, _floor, env in scored
    }
    floor_of = {
        _candidate_key(env): floor
        for _score, _sim, floor, env in scored
    }
    for _score, _sim, floor, env in scored:
        key = _candidate_key(env)
        if key in picked_keys or not floor:
            continue
        if len(out) < limit:
            out.append(env)
            picked_keys.add(key)
            continue
        replace_at = None
        worst: tuple[float, float] | None = None
        for i, row in enumerate(out):
            row_key = _candidate_key(row)
            if floor_of.get(row_key, _is_floor(row)):
                continue
            candidate_score = score_of.get(row_key, (0.0, 0.0))
            if worst is None or candidate_score < worst:
                worst = candidate_score
                replace_at = i
        if replace_at is None:
            break
        old_key = _candidate_key(out[replace_at])
        out[replace_at] = env
        picked_keys.discard(old_key)
        picked_keys.add(key)
    return out[:limit]


def _usable_hint_vectors(vectors: Any, expected_count: int) -> bool:
    if not isinstance(vectors, list) or len(vectors) != expected_count or not vectors:
        return False
    if any(not isinstance(vec, list) or not vec for vec in vectors):
        return False
    dimensions = {len(vec) for vec in vectors}
    return len(dimensions) == 1


def choose_candidates(
    context: dict[str, Any],
    state_root: Path,
    *,
    limit: int = 40,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    diagnostics: dict[str, Any] = {"embeddings_degraded": False}
    if limit <= 0:
        return [], diagnostics

    envelopes = [e for e in context.get("envelopes", []) if isinstance(e, dict)]
    structural = rank_thread_candidates(envelopes, max_threads=MAX_THREAD_CANDIDATES)
    if not structural:
        return [], diagnostics

    pack = load_active_pack(state_root)
    hints = pack.get("attention_hints", []) if pack else []
    hint_texts: list[str] = []
    for hint in hints:
        if isinstance(hint, dict):
            hint_texts.extend(str(u) for u in hint.get("utterances", []) if str(u).strip())
        elif isinstance(hint, str) and hint.strip():
            hint_texts.append(hint)

    # No semantic policy means structure-only selection, not an embedding outage.
    if not hint_texts:
        return rerank(structural[:limit]), diagnostics

    requested_hints = hint_texts[:8]
    try:
        hint_vecs = embed_texts(requested_hints)
        if not _usable_hint_vectors(hint_vecs, len(requested_hints)):
            raise ValueError("incomplete hint embedding response")

        thread_signals = _thread_signals(envelopes, structural)
        scored: list[ScoredCandidate] = []
        for env in structural:
            folder, uid = _candidate_key(env)
            vec = load_vector(state_root, folder, uid)
            sim = max(cosine(vec, hint_vec) for hint_vec in hint_vecs) if vec else 0.0
            thread_key = normalize_thread_key(env.get("subject"))
            structure_score, floor = thread_signals.get(
                thread_key,
                (_structure_score(env), _is_floor(env)),
            )
            scored.append((_hybrid_score(structure_score, sim), sim, floor, env))
    except Exception:
        diagnostics["embeddings_degraded"] = True
        return rerank(structural[:limit]), diagnostics

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    picked = [env for _score, _sim, _floor, env in scored[:limit]]
    picked = _apply_recall_floor(picked, scored, limit=limit)
    return rerank(picked), diagnostics

def semantic_search(query: str, state_root: Path, *, limit: int = 5) -> list[dict[str, Any]]:
    from .pulse import load_activity_pulse

    try:
        qvec = embed_texts([query])[0]
    except Exception:
        return []
    pulse = load_activity_pulse(state_root)
    out: list[dict[str, Any]] = []
    for item in pulse.get("thread_index", []):
        if not isinstance(item, dict):
            continue
        ref = str(item.get("latest_message_ref", "") or "")
        if "#" not in ref:
            continue
        folder, uid = ref.split("#", 1)
        vec = load_vector(state_root, folder, uid)
        if not vec:
            continue
        score = cosine(qvec, vec)
        if score <= 0:
            continue
        row = dict(item)
        row["match_score"] = int(score * 100)
        row["thread_key"] = normalize_thread_key(row.get("thread_key", ""))
        out.append(row)
    out.sort(key=lambda r: int(r.get("match_score", 0)), reverse=True)
    return rerank(out, query=query)[:limit]
