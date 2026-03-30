"""Tests for IMAP modified UTF-7 mailbox encoding and quoting."""

from __future__ import annotations

from twinbox_core.imap_utf7 import decode_utf7, encode_utf7, mailbox_for_wire


def test_encode_ampersand_in_ascii_name() -> None:
    assert encode_utf7("Fun&uns") == b"Fun&-uns"
    assert decode_utf7(b"Fun&-uns") == "Fun&uns"


def test_inbox_unchanged() -> None:
    assert mailbox_for_wire("INBOX") == "INBOX"
    assert mailbox_for_wire("  INBOX  ") == "INBOX"


def test_non_ascii_roundtrip() -> None:
    for s in ("日本語", "Входящие", "收件箱"):
        w = mailbox_for_wire(s)
        assert w.encode("ascii")
        assert decode_utf7(w.encode("ascii")) == s


def test_names_with_spaces_are_quoted() -> None:
    """Folder names with spaces must become IMAP quoted-strings (RFC 3501)."""
    assert mailbox_for_wire("Sent Items") == '"Sent Items"'
    assert mailbox_for_wire("Junk E-mail") == '"Junk E-mail"'
    assert mailbox_for_wire("Virus Items") == '"Virus Items"'


def test_plain_ascii_atom_names_unchanged() -> None:
    for name in ("INBOX", "Drafts", "Trash", "Notes", "Sent"):
        assert mailbox_for_wire(name) == name
        assert '"' not in mailbox_for_wire(name)


def test_non_ascii_without_spaces_is_utf7_atom() -> None:
    """Non-ASCII names encode to modified UTF-7 which contains only atom-safe chars."""
    for s in ("辽宁", "收件箱"):
        w = mailbox_for_wire(s)
        assert w.startswith("&") or w.endswith("-")
        assert " " not in w
        assert '"' not in w
