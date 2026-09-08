"""Recipient role unit tests."""

from __future__ import annotations

import unittest

from twinbox_core.recipient import aggregate_thread_recipient_role, parse_envelope_recipient_role


class TestRecipientRole(unittest.TestCase):
    def test_to_hit(self) -> None:
        self.assertEqual(
            parse_envelope_recipient_role(owner_addr="me@corp.com", to="me@corp.com", cc=""),
            "to",
        )

    def test_cc_only(self) -> None:
        self.assertEqual(
            parse_envelope_recipient_role(owner_addr="me@corp.com", to="a@x.com", cc="me@corp.com"),
            "cc",
        )

    def test_group_only(self) -> None:
        self.assertEqual(
            parse_envelope_recipient_role(
                owner_addr="me@corp.com", to="list@x.com", cc="", list_id="<all@x.com>"
            ),
            "group",
        )


class TestAggregate(unittest.TestCase):
    def test_direct(self) -> None:
        self.assertEqual(aggregate_thread_recipient_role([{"recipient_role": "to"}]), "direct")


if __name__ == "__main__":
    unittest.main()
