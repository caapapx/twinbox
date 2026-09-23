"""US4 optional axes: waiting party and deadline project with evidence_refs."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from twinbox_core.pulse import normalize_thread_key, write_activity_pulse

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _seed(root: Path, *, subject: str, row: dict) -> str:
    tk = normalize_thread_key(subject)
    when = datetime.now(SHANGHAI) - timedelta(hours=2)
    env = {
        "id": "7",
        "folder": "INBOX",
        "subject": subject,
        "date": when.isoformat(timespec="seconds"),
        "flags": [],
        "from_addr": "boss@example.com",
        "recipient_role": "to",
    }
    raw_dir = root / "runtime" / "validation" / "phase-1" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "envelopes-merged.json").write_text(
        json.dumps([env], ensure_ascii=False), encoding="utf-8"
    )
    ctx = root / "runtime" / "context" / "phase1-context.json"
    ctx.parent.mkdir(parents=True, exist_ok=True)
    ctx.write_text(json.dumps({"envelopes": [env], "sampled_bodies": {}}), encoding="utf-8")
    fields = dict(row)
    fields.setdefault("thread_key", tk)
    phase4 = root / "runtime" / "validation" / "phase-4"
    phase4.mkdir(parents=True, exist_ok=True)
    (phase4 / "daily-urgent.yaml").write_text(
        "generated_at: '2030-01-10T08:00:00+08:00'\ndaily_urgent:\n  - "
        + json.dumps(fields, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return tk


def _projection(payload: dict, tk: str) -> dict | None:
    for bucket in ("action_required", "watch", "reference"):
        for row in (payload.get("projections") or {}).get(bucket) or []:
            if row.get("thread_key") == tk:
                return row
    return None


class TestOptionalAxes(unittest.TestCase):
    def test_waiting_on_projects_axis_and_evidence_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tk = _seed(root, subject="Deploy review", row={
                "waiting_on": "何诚",
                "evidence_refs": ["INBOX#7"],
                "why": "need reply",
            })
            payload, _ = write_activity_pulse(root)
            row = _projection(payload, tk)
            self.assertIsNotNone(row)
            self.assertEqual(row["waiting_on"]["value"], "何诚")
            self.assertEqual(row["waiting_on"]["evidence_refs"], ["INBOX#7"])
            self.assertNotIn("deadline", row)

    def test_deadline_projects_axis_and_evidence_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tk = _seed(root, subject="Budget sign", row={
                "deadline": "2026-09-25T18:00:00+08:00",
                "evidence_refs": ["INBOX#7"],
                "why": "due soon",
            })
            payload, _ = write_activity_pulse(root)
            row = _projection(payload, tk)
            self.assertIsNotNone(row)
            self.assertEqual(row["deadline"]["value"], "2026-09-25T18:00:00+08:00")
            self.assertEqual(row["deadline"]["evidence_refs"], ["INBOX#7"])
            self.assertNotIn("waiting_on", row)

    def test_neither_omits_both_axes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tk = _seed(root, subject="Notice", row={"why": "need reply"})
            payload, _ = write_activity_pulse(root)
            row = _projection(payload, tk)
            self.assertIsNotNone(row)
            self.assertNotIn("waiting_on", row)
            self.assertNotIn("deadline", row)


if __name__ == "__main__":
    unittest.main()
