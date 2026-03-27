"""Tests for envelope To/Cc field probing (Himalaya-shaped JSON)."""

from __future__ import annotations

import unittest
from typing import Any

from twinbox_core.envelope_recipient_probe import (
    normalize_addr_field,
    summarize_envelope,
)

# Inline Himalaya-shaped samples (previously under tests/fixtures/*.json).
_RICH_ENVELOPES: list[dict[str, Any]] = [
    {
        "id": "e0",
        "to": {"name": "Owner", "addr": "owner@example.com"},
        "cc": {"name": "Bob", "addr": "bob@example.com"},
    },
    {
        "id": "e1",
        "to": [
            {"addr": "a@example.com"},
            {"addr": "b@example.com"},
        ],
    },
    {
        "id": "e2",
        "List-Id": "<list.example.com>",
    },
]

_MINIMAL_NO_TO_CC: dict[str, Any] = {"id": "m1", "subject": "hello"}


class EnvelopeRecipientProbeTest(unittest.TestCase):
    def test_normalize_single_dict(self) -> None:
        got = normalize_addr_field({"name": "X", "addr": "A@B.COM"})
        self.assertEqual(got, [{"addr": "a@b.com", "name": "X"}])

    def test_normalize_list(self) -> None:
        got = normalize_addr_field(
            [
                {"addr": "a@x.com"},
                {"name": "only"},
            ]
        )
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["addr"], "a@x.com")

    def test_summarize_fixture_direct_and_cc(self) -> None:
        s0 = summarize_envelope(_RICH_ENVELOPES[0])
        self.assertEqual(s0["to_entry_count"], 1)
        self.assertEqual(s0["cc_entry_count"], 1)
        self.assertIn("owner@example.com", s0["to_addrs"])
        self.assertIn("bob@example.com", s0["cc_addrs"])
        self.assertFalse(s0["has_list_id_key"])

    def test_summarize_fixture_multi_to(self) -> None:
        s1 = summarize_envelope(_RICH_ENVELOPES[1])
        self.assertEqual(s1["to_entry_count"], 2)
        self.assertEqual(s1["cc_entry_count"], 0)

    def test_summarize_fixture_list_id(self) -> None:
        s2 = summarize_envelope(_RICH_ENVELOPES[2])
        self.assertTrue(s2["has_list_id_key"])

    def test_delivery_fixture_minimal_has_no_to_cc(self) -> None:
        s = summarize_envelope(_MINIMAL_NO_TO_CC)
        self.assertEqual(s["to_entry_count"], 0)
        self.assertEqual(s["cc_entry_count"], 0)


if __name__ == "__main__":
    unittest.main()
