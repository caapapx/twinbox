"""Optional shared IMAP SSL connection for repeated probes (preflight).

Enable with ``TWINBOX_IMAP_POOL=1``. Falls back to normal himalaya path on failure.
"""

from __future__ import annotations

import imaplib
import os
import threading
from typing import Any

from .imap_utf7 import mailbox_for_wire

_lock = threading.Lock()
_holder: tuple[tuple[str, int, str], imaplib.IMAP4_SSL] | None = None


def reset_pool_for_tests() -> None:
    global _holder
    with _lock:
        if _holder is not None:
            try:
                _holder[1].logout()
            except Exception:
                pass
            _holder = None


def _alive(conn: imaplib.IMAP4_SSL) -> bool:
    try:
        conn.noop()
        return True
    except Exception:
        return False


def imap_pool_enabled() -> bool:
    return os.environ.get("TWINBOX_IMAP_POOL", "").strip() in ("1", "true", "yes")


def get_shared_imap(host: str, port: int, user: str, password: str) -> imaplib.IMAP4_SSL:
    global _holder
    key = (host, int(port), user)
    with _lock:
        if _holder is not None and _holder[0] == key and _alive(_holder[1]):
            return _holder[1]
        if _holder is not None:
            try:
                _holder[1].logout()
            except Exception:
                pass
        conn = imaplib.IMAP4_SSL(host, int(port))
        conn.login(user, password)
        _holder = (key, conn)
        return conn


def imap_probe_select_folder(effective_env: dict[str, str], folder: str) -> tuple[bool, str]:
    """LOGIN + SELECT *folder* (readonly). Returns (ok, detail)."""
    try:
        host = (effective_env.get("IMAP_HOST") or "").strip()
        port = int((effective_env.get("IMAP_PORT") or "993").strip() or "993")
        user = (effective_env.get("IMAP_LOGIN") or "").strip()
        password = (effective_env.get("IMAP_PASS") or "").strip()
        if not host or not user:
            return False, "missing IMAP_HOST or IMAP_LOGIN"
        conn = get_shared_imap(host, port, user, password)
        typ, data = conn.select(mailbox_for_wire(folder), readonly=True)
        if typ != "OK":
            return False, f"IMAP SELECT failed: {typ} {data!r}"
        return True, "imap_select_ok"
    except Exception as exc:
        return False, str(exc)


def pool_stats() -> dict[str, Any]:
    with _lock:
        active = _holder is not None and _alive(_holder[1])
        return {"enabled": imap_pool_enabled(), "pooled": active}
