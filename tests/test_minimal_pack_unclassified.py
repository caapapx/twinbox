"""Shipped minimal pack: attention phrases stay unclassified and unmerged."""

import tempfile
import unittest
from pathlib import Path

from twinbox_core import events


class TestShippedMinimalPack(unittest.TestCase):
    def test_same_subject_stays_two_unknown_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rows = events.extract_events({
                "source_account": "acct",
                "envelopes": [
                    {"id": "41", "folder": "INBOX", "subject": "请审批 预警"},
                    {"id": "39", "folder": "INBOX", "subject": "请审批 预警"},
                ],
            }, Path(tmp))
        self.assertEqual([row["mail_ref"]["uid"] for row in rows], ["41", "39"])
        for row in rows:
            self.assertEqual(row["classification_status"], "unknown")
            self.assertIsNone(row["semantics"]["primary_event_type"])
            self.assertEqual(row["type"], "unclassified")


if __name__ == "__main__":
    unittest.main()
