"""Self-hosted embedding client + JSON sidecar cosine (ADR-003)."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any
from urllib import error, request


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _embed_dir(state_root: Path) -> Path:
    return state_root / "runtime" / "context" / "embeddings"


def sidecar_path(state_root: Path, folder: str, uid: str) -> Path:
    safe_folder = folder.replace("/", "_")
    return _embed_dir(state_root) / f"{safe_folder}_{uid}.json"


def resolve_embedding_config() -> dict[str, Any] | None:
    from .config import load_config

    cfg = load_config().get("embeddings", {})
    if not isinstance(cfg, dict):
        cfg = {}
    url = str(cfg.get("api_url") or os.environ.get("TWINBOX_EMBED_URL", "") or "").strip()
    model = str(cfg.get("model") or os.environ.get("TWINBOX_EMBED_MODEL", "") or "").strip()
    if not url or not model:
        return None
    return {
        "api_url": url,
        "model": model,
        "api_key": str(cfg.get("api_key") or os.environ.get("TWINBOX_EMBED_KEY", "") or ""),
        "timeout": int(cfg.get("timeout", 60) or 60),
    }


def embed_texts(texts: list[str]) -> list[list[float]]:
    cfg = resolve_embedding_config()
    if not cfg:
        raise RuntimeError("embedding endpoint not configured")
    payload = json.dumps({"model": cfg["model"], "input": texts}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = request.Request(cfg["api_url"], data=payload, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=cfg["timeout"]) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(str(exc)) from exc
    data = body.get("data", [])
    if not isinstance(data, list):
        raise RuntimeError("unexpected embedding response")
    out: list[list[float]] = []
    for row in sorted(data, key=lambda r: int(r.get("index", 0)) if isinstance(r, dict) else 0):
        if isinstance(row, dict):
            vec = row.get("embedding") or []
            out.append([float(x) for x in vec])
    return out


def embed_new_messages(state_root: Path, envelopes: list[dict[str, Any]], body_map: dict[str, Any]) -> dict[str, Any]:
    pending: list[tuple[str, str, str]] = []
    for env in envelopes:
        folder = str(env.get("folder", "INBOX") or "INBOX")
        uid = str(env.get("id", "") or "")
        path = sidecar_path(state_root, folder, uid)
        if path.is_file() or not uid:
            continue
        key = f"{folder}#{uid}"
        entry = body_map.get(key) or body_map.get(uid) or {}
        body = ""
        if isinstance(entry, dict):
            body = str(entry.get("body", "") or "")
        elif isinstance(entry, str):
            body = entry
        text = f"{env.get('subject', '')}\n{body[:800]}"
        pending.append((folder, uid, text))
    if not pending:
        return {"ok": True, "embedded": 0}
    try:
        vectors = embed_texts([t for _f, _u, t in pending])
    except Exception:
        return {"ok": False, "embedded": 0, "degraded": True}
    _embed_dir(state_root).mkdir(parents=True, exist_ok=True)
    cfg = resolve_embedding_config() or {}
    for (folder, uid, text), vec in zip(pending, vectors):
        sidecar_path(state_root, folder, uid).write_text(
            json.dumps({
                "folder": folder,
                "uid": uid,
                "model": cfg.get("model", ""),
                "dimensions": len(vec),
                "text_fingerprint": str(len(text)),
                "vector": vec,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
    return {"ok": True, "embedded": len(vectors)}


def load_vector(state_root: Path, folder: str, uid: str) -> list[float] | None:
    path = sidecar_path(state_root, folder, uid)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    vec = data.get("vector") if isinstance(data, dict) else None
    if not isinstance(vec, list):
        return None
    return [float(x) for x in vec]


def resolve_rerank_config() -> dict[str, Any] | None:
    from .config import load_config

    cfg = load_config().get("rerank", {})
    if not isinstance(cfg, dict):
        cfg = {}
    url = str(cfg.get("api_url") or os.environ.get("TWINBOX_RERANK_URL", "") or "").strip()
    model = str(cfg.get("model") or os.environ.get("TWINBOX_RERANK_MODEL", "") or "").strip()
    if not url:
        return None
    return {
        "api_url": url,
        "model": model or "Qwen3-Reranker-8B",
        "api_key": str(cfg.get("api_key") or os.environ.get("TWINBOX_RERANK_KEY", "") or ""),
        "timeout": int(cfg.get("timeout", 60) or 60),
    }


def rerank(candidates: list[dict[str, Any]], query: str = "") -> list[dict[str, Any]]:
    """Identity unless rerank.api_url is set (optional rerank endpoint)."""
    cfg = resolve_rerank_config()
    if not cfg or not query or len(candidates) < 2:
        return candidates
    docs: list[str] = []
    for row in candidates:
        docs.append(str(row.get("latest_subject") or row.get("subject") or row.get("why") or ""))
    payload = json.dumps({"model": cfg["model"], "query": query, "documents": docs}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = request.Request(cfg["api_url"], data=payload, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=cfg["timeout"]) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError):
        return candidates
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        return candidates
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        idx = int(item.get("index", -1))
        if 0 <= idx < len(candidates):
            scored.append((float(item.get("relevance_score") or item.get("score") or 0), candidates[idx]))
    if not scored:
        return candidates
    scored.sort(key=lambda p: p[0], reverse=True)
    return [row for _s, row in scored]
