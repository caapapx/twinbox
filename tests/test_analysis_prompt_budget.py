from __future__ import annotations

import os
import unittest
from unittest import mock


class TestAnalysisPromptBudget(unittest.TestCase):
    def _context(self) -> dict:
        envelopes = []
        sampled_bodies = {}
        for thread_no in range(3):
            subject = f"业务线程-{thread_no}"
            for message_no in range(2):
                uid = f"{thread_no}-{message_no}"
                envelopes.append(
                    {
                        "subject": subject if message_no == 0 else f"Re: {subject}",
                        "date": f"2026-09-{10 + message_no:02d}T10:00:00+08:00",
                        "id": uid,
                        "folder": "INBOX",
                        "flags": [],
                        "recipient_role": "to",
                        "from_name": "sender",
                        "from_addr": "sender@example.test",
                    }
                )
                sampled_bodies[f"INBOX#{uid}"] = {
                    "body": (f"body-{thread_no}-{message_no}-" + "x" * 4000)
                }
        return {
            "lookback_days": 30,
            "owner_domain": "example.test",
            "envelopes": envelopes,
            "sampled_bodies": sampled_bodies,
        }

    def test_hard_budget_prefers_latest_bodies_and_keeps_latest_refs(self) -> None:
        from twinbox_core.analyze import _build_prompt

        context = self._context()
        with mock.patch.dict(os.environ, {"TWINBOX_ANALYSIS_PROMPT_MAX_CHARS": "2200"}):
            prompt = _build_prompt(context)

        self.assertLessEqual(len(prompt), 2200)
        stats = context["stats"]
        self.assertTrue(stats["prompt_truncated"])
        self.assertEqual(stats["prompt_char_limit"], 2200)
        self.assertEqual(stats["prompt_threads"], 3)
        self.assertEqual(stats["prompt_messages"], 6)
        self.assertGreater(stats["prompt_body_messages_available"], stats["prompt_body_messages_included"])
        for thread_no in range(3):
            # Latest is message 1 because the date sort is descending.
            self.assertIn(f"evidence_id=INBOX#{thread_no}-1", prompt)

    def test_untruncated_prompt_reports_exact_size_and_body_counts(self) -> None:
        from twinbox_core.analyze import _build_prompt

        context = self._context()
        with mock.patch.dict(os.environ, {"TWINBOX_ANALYSIS_PROMPT_MAX_CHARS": "20000"}):
            prompt = _build_prompt(context)

        stats = context["stats"]
        self.assertEqual(len(prompt), stats["prompt_chars"])
        self.assertLessEqual(stats["prompt_chars"], stats["prompt_char_limit"])
        self.assertFalse(stats["prompt_truncated"])
        self.assertEqual(stats["prompt_body_messages_available"], 6)
        self.assertEqual(stats["prompt_body_messages_included"], 6)
        self.assertEqual(stats["prompt_body_messages_omitted"], 0)
        self.assertIn("body_preview evidence_id=INBOX#0-1", prompt)
        self.assertIn("body_available=true", prompt)

    def test_invalid_or_excessive_budget_is_clamped(self) -> None:
        from twinbox_core.analyze import _build_prompt

        context = {"envelopes": []}
        with mock.patch.dict(os.environ, {"TWINBOX_ANALYSIS_PROMPT_MAX_CHARS": "not-a-number"}):
            _build_prompt(context)
        self.assertEqual(context["stats"]["prompt_char_limit"], 1_000_000)

        context = {"envelopes": []}
        with mock.patch.dict(os.environ, {"TWINBOX_ANALYSIS_PROMPT_MAX_CHARS": "999999999"}):
            _build_prompt(context)
        self.assertEqual(context["stats"]["prompt_char_limit"], 4_000_000)


if __name__ == "__main__":
    unittest.main()
