"""Process-wide daemon metrics (connection counts)."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_active_conns = 0


def adjust_active(delta: int) -> None:
    global _active_conns
    with _lock:
        _active_conns += delta


def active_connection_count() -> int:
    with _lock:
        return _active_conns
