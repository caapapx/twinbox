"""IMAP modified UTF-7 (RFC 2152) for mailbox names (RFC 3501 §5.1.3).

Python :mod:`imaplib` sends mailbox arguments as raw bytes without quoting.
Two problems need fixing before calling :meth:`imaplib.IMAP4.select`:

1. Non-ASCII chars must be encoded in modified UTF-7 (RFC 3501 §5.1.3).
2. Names containing spaces or IMAP atom-special characters (SP, ``()``,
   ``{}``, ``%*\\"`` plus CTL) must be wrapped in IMAP quoted-string syntax,
   otherwise the server sees a malformed command such as ``EXAMINE Sent Items``
   and returns ``BAD Request not ending with``.
"""

from __future__ import annotations

import binascii
from typing import List

# RFC 3501 §9 atom-specials: ( ) { SP CTL % * \ "
# We also exclude ] which is resp-special, for safety.
# Characters NOT in this set are valid IMAP atom chars.
_IMAP_NEEDS_QUOTING: frozenset[int] = frozenset(
    b"() {}%*\\\"]\x7f" + bytes(range(0x20))  # space + specials + CTL
)


def encode_utf7(s: str) -> bytes:
    """Encode a Unicode mailbox name to IMAP modified UTF-7 (bytes, ASCII-only)."""
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


def decode_utf7(raw: bytes) -> str:
    """Decode modified UTF-7 mailbox name to Unicode."""
    out: List[str] = []
    i = 0
    n = len(raw)
    while i < n:
        b = raw[i]
        if b == 0x26:
            if i + 1 < n and raw[i + 1] == 0x2D:
                out.append("&")
                i += 2
                continue
            j = i + 1
            while j < n and raw[j] != 0x2D:
                j += 1
            if j >= n:
                out.append(raw[i:].decode("ascii", errors="replace"))
                break
            b64 = raw[i + 1 : j].replace(b",", b"/")
            pad = (-len(b64)) % 4
            if pad:
                b64 += b"=" * pad
            out.append(binascii.a2b_base64(b64).decode("utf-16be"))
            i = j + 1
            continue
        out.append(chr(b))
        i += 1
    return "".join(out)


def _imap_quote(s: str) -> str:
    """Wrap *s* in IMAP quoted-string syntax, escaping ``\\`` and ``"``."""
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def mailbox_for_wire(display_name: str) -> str:
    """Encode a folder display-name for :meth:`imaplib.IMAP4.select`.

    Applies IMAP modified UTF-7 for non-ASCII characters, then wraps the
    result in double-quotes when the encoded name contains characters that are
    not valid in an IMAP atom (e.g. ``Sent Items`` must become
    ``"Sent Items"`` so the server receives a valid quoted-string argument).
    """
    name = display_name.strip()
    if not name:
        return name
    encoded = encode_utf7(name).decode("ascii")
    if any(ord(c) in _IMAP_NEEDS_QUOTING for c in encoded):
        return _imap_quote(encoded)
    return encoded
