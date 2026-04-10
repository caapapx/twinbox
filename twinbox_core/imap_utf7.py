"""IMAP modified UTF-7 (RFC 2152) for mailbox names (RFC 3501 §5.1.3).

Python :mod:`imaplib` sends mailbox arguments as raw bytes without quoting.
Two problems need fixing before calling :meth:`imaplib.IMAP4.select`:

1. Non-ASCII chars must be encoded in modified UTF-7 (RFC 3501 §5.1.3).
2. Names containing spaces or IMAP atom-special characters (SP, ``()``,
   ``{}``, ``%*\\"``) must be wrapped in IMAP quoted-string syntax.
"""

from __future__ import annotations

import binascii
from typing import List

_IMAP_NEEDS_QUOTING: frozenset[int] = frozenset(
    b"() {}%*\\\"]\\x7f" + bytes(range(0x20))
)


def encode_utf7(s: str) -> bytes:
    res = bytearray()
    pending: List[str] = []

    def flush() -> None:
        if not pending:
            return
        chunk = "".join(pending).encode("utf-16be")
        b64 = binascii.b2a_base64(chunk).rstrip(b"\n=").replace(b"/", b",")
        res.extend(b"&" + b64 + b"-")
        pending.clear()

    for c in s:
        o = ord(c)
        if 0x20 <= o <= 0x7E:
            flush()
            if o == 0x26:
                res.extend(b"&-")
            else:
                res.append(o)
        else:
            pending.append(c)
    flush()
    return bytes(res)


def mailbox_for_wire(display_name: str) -> str:
    name = display_name.strip()
    if not name:
        return name
    encoded = encode_utf7(name).decode("ascii")
    if any(ord(c) in _IMAP_NEEDS_QUOTING for c in encoded):
        escaped = encoded.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return encoded
