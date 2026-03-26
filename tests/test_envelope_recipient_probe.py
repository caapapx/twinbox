"""Tests for envelope To/Cc field probing (Himalaya-shaped JSON)."""

from __future__ import annotations

import json
from pathlib import Path

import unittest

from twinbox_core.envelope_recipient_probe import (
    load_envelope_array,
    normalize_addr_field,
    summarize_envelope,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "himalaya_envelope_rich_sample.json"


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
        envs = load_envelope_array(FIXTURE)
        s0 = summarize_envelope(envs[0])
        self.assertEqual(s0["to_entry_count"], 1)
        self.assertEqual(s0["cc_entry_count"], 1)
        self.assertIn("owner@example.com", s0["to_addrs"])
        self.assertIn("bob@example.com", s0["cc_addrs"])
        self.assertFalse(s0["has_list_id_key"])

    def test_summarize_fixture_multi_to(self) -> None:
        envs = load_envelope_array(FIXTURE)
        s1 = summarize_envelope(envs[1])
        self.assertEqual(s1["to_entry_count"], 2)
        self.assertEqual(s1["cc_entry_count"], 0)

    def test_summarize_fixture_list_id(self) -> None:
        envs = load_envelope_array(FIXTURE)
        s2 = summarize_envelope(envs[2])
        self.assertTrue(s2["has_list_id_key"])

    def test_delivery_fixture_minimal_has_no_to_cc(self) -> None:
        minimal = Path(__file__).resolve().parent / "fixtures" / "delivery_director_ops" / "envelopes.json"
        raw = json.loads(minimal.read_text(encoding="utf-8"))
        self.assertIsInstance(raw, list)
        first = raw[0]
        assert isinstance(first, dict)
        s = summarize_envelope(first)
        self.assertEqual(s["to_entry_count"], 0)
        self.assertEqual(s["cc_entry_count"], 0)


if __name__ == "__main__":
    unittest.main()
