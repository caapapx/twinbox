"""Candidate thread selection: structure + pack attention_hints cosine."""

from __future__ import annotations

from typing import Any
from pathlib import Path

from .embeddings import cosine, embed_texts, load_vector, rerank
from .imap_fetch import MAX_THREAD_CANDIDATES, rank_thread_candidates
from .pack import load_active_pack
from .pulse import normalize_thread_key


def choose_candidates(
    context: dict[str, Any],
    state_root: Path,
    *,
    limit: int = 40,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    envelopes = [e for e in context.get("envelopes", []) if isinstance(e, dict)]
    diagnostics: dict[str, Any] = {"embeddings_degraded": False}
    structural = rank_thread_candidates(envelopes, max_threads=MAX_THREAD_CANDIDATES)
    pack = load_active_pack(state_root)
    hints = pack.get("attention_hints", []) if pack else []
    hint_texts = []
    for hint in hints:
        if isinstance(hint, dict):
            hint_texts.extend(str(u) for u in hint.get("utterances", []) if str(u).strip())
        elif isinstance(hint, str):
            hint_texts.append(hint)
    scored: list[tuple[float, dict[str, Any]]] = []
    hint_vecs: list[list[float]] = []
    if hint_texts:
        try:
            hint_vecs = embed_texts(hint_texts[:8])
        except Exception:
            diagnostics["embeddings_degraded"] = True
    for env in structural:
        folder = str(env.get("folder", "INBOX") or "INBOX")
        uid = str(env.get("id", "") or "")
        sim = 0.0
        vec = load_vector(state_root, folder, uid)
        if vec and hint_vecs:
            sim = max(cosine(vec, hv) for hv in hint_vecs)
        scored.append((sim, env))
    if hint_vecs and not diagnostics["embeddings_degraded"]:
        scored.sort(key=lambda p: p[0], reverse=True)
        picked = [env for _s, env in scored[:limit]]
    else:
        picked = structural[:limit]
        if not hint_vecs:
            diagnostics["embeddings_degraded"] = diagnostics["embeddings_degraded"] or not bool(resolve_ok())
    return rerank(picked), diagnostics


def resolve_ok() -> bool:
    from .embeddings import resolve_embedding_config
    return resolve_embedding_config() is not None


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
    return rerank(out)[:limit]
