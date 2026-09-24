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

    def test_hour_filter(self) -> None:
        criteria = ExtractCriteria(from_hour=17, to_hour=24)
        morning = _env("个人周报", when=datetime(2025, 6, 6, 10, 0, tzinfo=SHANGHAI))
        evening = _env("个人周报", when=datetime(2025, 6, 6, 18, 0, tzinfo=SHANGHAI))
        self.assertFalse(matches_envelope(morning, criteria))
        self.assertTrue(matches_envelope(evening, criteria))

    def test_report_has_no_mime_headers(self) -> None:
        report = envelope_to_report(
            _env("个人周报", when=datetime(2025, 6, 6, 18, 0, tzinfo=SHANGHAI), body="正文不含Content-Type"),
            bucket="iso_week",
        )
        self.assertNotIn("Content-Type:", report["body_text"])
        self.assertIn("attachments", report)


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
        self.assertTrue(any("Sent" in f for f in criteria.folders))
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


class TestExtractAccount(unittest.TestCase):
    def test_run_extract_passes_account_id_to_imap_config(self) -> None:
        from unittest import mock
        from twinbox_core.extract import run_extract

        seen: dict[str, str | None] = {}

        def fake_resolve(account_id=None):
            seen["account_id"] = account_id
            return {"host": "h", "login": "acct-b@example.com", "password": "x", "port": 993, "encryption": "tls"}

        with mock.patch("twinbox_core.extract.resolve_imap_config", side_effect=fake_resolve), \
             mock.patch("twinbox_core.extract.fetch_by_query", return_value=([], [])), \
             mock.patch("twinbox_core.extract.owner_email", return_value=""):
            from pathlib import Path
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                result = run_extract(
                    Path(tmp),
                    ExtractCriteria(since=date(2026, 9, 1), folders=["INBOX"], fetch_bodies=False),
                    account_id="acct-b",
                )
        self.assertEqual(seen["account_id"], "acct-b")
        self.assertEqual(result["result"], "no_match")
        self.assertEqual(result["matched_count"], 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["source_used"], "imap")


class TestLocalSource(unittest.TestCase):
    def test_plain_since_leaves_weekdays_unset(self) -> None:
        criteria = merge_criteria(ExtractCriteria(), {"since": "2026-09-01"})
        self.assertIsNone(criteria.weekdays)
        self.assertEqual(criteria.source, "auto")

    def test_auto_in_retention_skips_imap(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock
        from twinbox_core.extract import run_extract

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "runtime" / "validation" / "phase-1" / "raw"
            raw.mkdir(parents=True)
            (raw / "envelopes-merged.json").write_text(json.dumps([
                {
                    "id": "9",
                    "folder": "INBOX",
                    "subject": "上周周报",
                    "date": "2026-09-15T10:00:00+08:00",
                    "from_addr": "a@x",
                }
            ]), encoding="utf-8")
            with mock.patch("twinbox_core.extract.fetch_by_query") as fetch, \
                 mock.patch("twinbox_core.extract.owner_email", return_value=""):
                result = run_extract(
                    root,
                    ExtractCriteria(
                        since=date(2026, 9, 15),
                        until=date(2026, 9, 22),
                        folders=["INBOX"],
                        subject_contains=["周报"],
                        fetch_bodies=False,
                        source="auto",
                    ),
                )
            fetch.assert_not_called()
            self.assertEqual(result["source_used"], "local")
            self.assertEqual(result["matched_count"], 1)

    def test_local_outside_retention_still_skips_imap(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock
        from twinbox_core.extract import run_extract

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "runtime" / "validation" / "phase-1" / "raw"
            raw.mkdir(parents=True)
            (raw / "envelopes-merged.json").write_text(json.dumps([
                {
                    "id": "9",
                    "folder": "INBOX",
                    "subject": "近期",
                    "date": "2026-09-15T10:00:00+08:00",
                    "from_addr": "a@x",
                }
            ]), encoding="utf-8")
            with mock.patch("twinbox_core.extract.fetch_by_query") as fetch, \
                 mock.patch("twinbox_core.extract.owner_email", return_value=""):
                result = run_extract(
                    root,
                    ExtractCriteria(
                        since=date(2026, 1, 1),
                        folders=["INBOX"],
                        fetch_bodies=False,
                        source="local",
                    ),
                )
            fetch.assert_not_called()
            self.assertEqual(result["source_used"], "local")
            self.assertEqual(result["matched_count"], 1)
            self.assertNotIn("result", result)

    def test_imap_source_calls_fetch(self) -> None:
        from pathlib import Path
        import tempfile
        from unittest import mock
        from twinbox_core.extract import run_extract

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("twinbox_core.extract.resolve_imap_config", return_value={"host": "h", "login": "a", "password": "x"}), \
             mock.patch("twinbox_core.extract.fetch_by_query", return_value=([], [])) as fetch, \
             mock.patch("twinbox_core.extract.owner_email", return_value=""):
            result = run_extract(
                Path(tmp),
                ExtractCriteria(since=date(2026, 9, 1), folders=["INBOX"], fetch_bodies=False, source="imap"),
            )
        fetch.assert_called_once()
        self.assertEqual(result["source_used"], "imap")

    def test_imap_subject_filter_stays_local(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest import mock
        from twinbox_core.extract import run_extract

        rows = [
            _env("个人周报", when=datetime(2025, 7, 15, 10, 0, tzinfo=SHANGHAI)),
            _env("采购通知", when=datetime(2025, 7, 16, 10, 0, tzinfo=SHANGHAI)),
        ]
        rows[0]["folder"] = "INBOX"
        rows[1]["folder"] = "INBOX"
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("twinbox_core.extract.resolve_imap_config", return_value={"host": "h", "login": "a", "password": "x"}), \
             mock.patch("twinbox_core.extract.fetch_by_query", return_value=(rows, [])) as fetch, \
             mock.patch("twinbox_core.extract.owner_email", return_value=""):
            result = run_extract(
                Path(tmp),
                ExtractCriteria(
                    since=date(2025, 7, 1),
                    until=date(2025, 8, 1),
                    folders=["INBOX"],
                    subject_contains=["周报"],
                    fetch_bodies=False,
                    source="imap",
                ),
            )
        self.assertIsNone(fetch.call_args.kwargs.get("subject_terms"))
        self.assertEqual(result["fetched_count"], 2)
        self.assertEqual(result["matched_count"], 1)
        self.assertEqual(result["reports"][0]["subject"], "个人周报")

    def test_until_is_exclusive(self) -> None:
        criteria = ExtractCriteria(since=date(2025, 7, 1), until=date(2025, 8, 1))
        inside = _env("a", when=datetime(2025, 7, 31, 23, 0, tzinfo=SHANGHAI))
        edge = _env("b", when=datetime(2025, 8, 1, 0, 0, tzinfo=SHANGHAI))
        self.assertTrue(matches_envelope(inside, criteria))
        self.assertFalse(matches_envelope(edge, criteria))

    def test_empty_imap_is_no_match(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest import mock
        from twinbox_core.extract import run_extract

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("twinbox_core.extract.resolve_imap_config", return_value={"host": "h", "login": "a", "password": "x"}), \
             mock.patch("twinbox_core.extract.fetch_by_query", return_value=([], [])) as fetch, \
             mock.patch("twinbox_core.extract.owner_email", return_value=""):
            result = run_extract(
                Path(tmp),
                ExtractCriteria(
                    since=date(2025, 7, 1),
                    folders=["INBOX"],
                    subject_contains=["周报"],
                    fetch_bodies=False,
                    source="imap",
                ),
            )
        fetch.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], "no_match")
        self.assertEqual(result["matched_count"], 0)


if __name__ == "__main__":
    unittest.main()
