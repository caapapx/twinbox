"""Unit tests for twinbox_core.extract (no live IMAP)."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from twinbox_core.extract import (
    ExtractCriteria,
    bucket_reports,
    envelope_to_report,
    matches_envelope,
    merge_criteria,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _env(subject: str, *, when: datetime, body: str = "", from_addr: str = "me@corp.com") -> dict:
    return {
        "id": "1",
        "folder": "Sent",
        "subject": subject,
        "from_addr": from_addr,
        "from_name": "Me",
        "date": when.isoformat(),
        "body": body,
    }


class TestSubjectMatching(unittest.TestCase):
    def setUp(self) -> None:
        self.criteria = ExtractCriteria(
            subject_contains=["周报", "Weekly"],
            subject_regex=[r".*的周报", r"\d{8}-\d{8}.*周报", r"\d{8}.*周报"],
        )
        self.friday = datetime(2025, 6, 6, 18, 0, tzinfo=SHANGHAI)

    def test_sample_titles_match(self) -> None:
        titles = [
            "张三的周报",
            "个人周报",
            "20260525-20260530-项目A周报",
        ]
        for title in titles:
            env = _env(title, when=self.friday)
            self.assertTrue(matches_envelope(env, self.criteria), title)

    def test_negative_subject(self) -> None:
        env = _env("月度总结会议通知", when=self.friday)
        self.assertFalse(matches_envelope(env, self.criteria))


class TestWeekdayFilter(unittest.TestCase):
    def test_friday_allowed(self) -> None:
        criteria = ExtractCriteria(weekdays=[4, 5, 6])
        env = _env("个人周报", when=datetime(2025, 6, 6, 10, 0, tzinfo=SHANGHAI))  # Fri
        self.assertTrue(matches_envelope(env, criteria))

    def test_wednesday_rejected(self) -> None:
        criteria = ExtractCriteria(weekdays=[4, 5, 6])
        env = _env("个人周报", when=datetime(2025, 6, 4, 10, 0, tzinfo=SHANGHAI))  # Wed
        self.assertFalse(matches_envelope(env, criteria))


class TestWeekBucket(unittest.TestCase):
    def test_different_weeks_get_different_week_of(self) -> None:
        r1 = envelope_to_report(
            _env("个人周报", when=datetime(2025, 6, 6, 10, 0, tzinfo=SHANGHAI)),
            bucket="iso_week",
        )
        r2 = envelope_to_report(
            _env("个人周报", when=datetime(2025, 6, 13, 10, 0, tzinfo=SHANGHAI)),
            bucket="iso_week",
        )
        self.assertNotEqual(r1["week_of"], r2["week_of"])

    def test_bucket_sorts_by_sent_at(self) -> None:
        reports = [
            {"sent_at": "2025-06-01T10:00:00+08:00", "subject": "a"},
            {"sent_at": "2025-06-15T10:00:00+08:00", "subject": "b"},
        ]
        out = bucket_reports(reports, "iso_week")
        self.assertGreater(out[0]["sent_at"], out[1]["sent_at"])


class TestProfileMerge(unittest.TestCase):
    def test_weekly_report_profile_loads(self) -> None:
        from pathlib import Path

        code_root = Path(__file__).resolve().parents[1]
        criteria = merge_criteria(
            ExtractCriteria(),
            {"profile": "weekly_report"},
            code_root=code_root,
        )
        self.assertEqual(criteria.profile, "weekly_report")
        self.assertIn("Sent", criteria.folders)
        self.assertIn("INBOX", criteria.folders)
        self.assertIsNotNone(criteria.since)
        self.assertEqual(criteria.weekdays, [4, 5, 6])

    def test_since_override(self) -> None:
        from pathlib import Path

        code_root = Path(__file__).resolve().parents[1]
        criteria = merge_criteria(
            ExtractCriteria(),
            {"profile": "weekly_report", "since": "2025-01-01"},
            code_root=code_root,
        )
        self.assertEqual(criteria.since, date(2025, 1, 1))


if __name__ == "__main__":
    unittest.main()
