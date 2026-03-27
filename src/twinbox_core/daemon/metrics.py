"""Process-wide daemon metrics (connection counts, cli_invoke cache)."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_active_conns = 0
_cache_hits = 0
_cache_misses = 0


def adjust_active(delta: int) -> None:
    global _active_conns
    with _lock:
        _active_conns += delta


def active_connection_count() -> int:
    with _lock:
        return _active_conns


def record_cache_hit() -> None:
    global _cache_hits
    with _lock:
        _cache_hits += 1


def record_cache_miss() -> None:
    global _cache_misses
    with _lock:
        _cache_misses += 1


def cache_counters() -> tuple[int, int]:
    with _lock:
        return _cache_hits, _cache_misses
