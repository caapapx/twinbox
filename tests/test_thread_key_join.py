"""thread_key join + recipient_role."""

from __future__ import annotations

import unittest

from twinbox_core.pulse import normalize_thread_key
from twinbox_core.recipient import aggregate_thread_recipient_role, parse_envelope_recipient_role


class TestThreadKey(unittest.TestCase):
    def test_strips_re_and_case(self) -> None:
        a = normalize_thread_key("Re: 验收登记")
        b = normalize_thread_key("RE: 验收登记")
        c = normalize_thread_key("回复: 验收登记")
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    def test_join_five_pending(self) -> None:
        keys = [
            "验收登记",
            "Re: 验收登记",
            "RE:验收登记",
            "回复：验收登记",
            "验收登记-20260903",
        ]
        normalized = {normalize_thread_key(k) for k in keys}
        self.assertEqual(len(normalized), 1)


class TestRecipientRole(unittest.TestCase):
    def test_to_is_to(self) -> None:
        self.assertEqual(
            parse_envelope_recipient_role(owner_addr="me@corp.com", to="Me <me@corp.com>", cc=""),
            "to",
        )

    def test_cc_only_message(self) -> None:
        self.assertEqual(
            parse_envelope_recipient_role(owner_addr="me@corp.com", to="other@x.com", cc="me@corp.com"),
            "cc",
        )

    def test_group_list_id(self) -> None:
        self.assertEqual(
            parse_envelope_recipient_role(
                owner_addr="me@corp.com", to="list@x.com", cc="", list_id="<all.example.com>"
            ),
            "group",
        )

    def test_thread_any_to_is_direct(self) -> None:
        role = aggregate_thread_recipient_role(
            [{"recipient_role": "cc"}, {"recipient_role": "to"}]
        )
        self.assertEqual(role, "direct")

    def test_cc_only_thread(self) -> None:
        self.assertEqual(aggregate_thread_recipient_role([{"recipient_role": "cc"}]), "cc_only")

    def test_group_only_thread(self) -> None:
        self.assertEqual(aggregate_thread_recipient_role([{"recipient_role": "group"}]), "group_only")


if __name__ == "__main__":
    unittest.main()
