"""In-process LRU cache for cli_invoke keyed by argv + context mtime fingerprint."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any

_MAX_ENTRIES = 64
_store: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()


def context_mtime_fingerprint(state_root: Path) -> str:
    ctx = state_root / "runtime" / "context"
    if not ctx.is_dir():
        return "no_context_dir"
    lines: list[str] = []
    for p in sorted(ctx.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        try:
            rel = p.relative_to(state_root)
            st = p.stat()
            lines.append(f"{rel.as_posix()}:{st.st_mtime_ns}")
        except OSError:
            continue
    blob = "\n".join(lines).encode()
    return hashlib.sha256(blob).hexdigest()[:40]


def _argv_key(argv: list[str]) -> str:
    return json.dumps(argv, separators=(",", ":"), ensure_ascii=False)


def cache_get(argv: list[str], fp: str) -> dict[str, Any] | None:
    k = (_argv_key(argv), fp)
    if k not in _store:
        return None
    _store.move_to_end(k)
    return dict(_store[k])


def cache_put(argv: list[str], fp: str, result: dict[str, Any]) -> None:
    k = (_argv_key(argv), fp)
    if k in _store:
        del _store[k]
    _store[k] = {k2: v2 for k2, v2 in result.items() if k2 in ("exit_code", "stdout", "stderr")}
    while len(_store) > _MAX_ENTRIES:
        _store.popitem(last=False)


def approx_size_mb() -> float:
    total = 0
    for v in _store.values():
        for part in (v.get("stdout"), v.get("stderr")):
            if isinstance(part, str):
                total += len(part.encode("utf-8", errors="ignore"))
    return round(total / (1024 * 1024), 4)
