"""Evidence validation: invented refs dropped; owner-action needs explicit evidence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from twinbox_core.analyze import run_analysis
from twinbox_core.project import project_item
from twinbox_core.pulse import write_activity_pulse


def _ctx(root: Path, envelopes: list[dict]) -> None:
    path = root / "runtime" / "context" / "phase1-context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"envelopes": envelopes, "lookback_days": 7}), encoding="utf-8")


class TestEvidenceValidation(unittest.TestCase):
    def test_invented_thread_and_ref_are_not_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _ctx(root, [{
                "subject": "部署评审",
                "id": "7",
                "folder": "INBOX",
                "date": "2026-09-18T10:00:00+08:00",
                "recipient_role": "direct",
            }])
            llm = json.dumps({
                "daily_urgent": [{
                    "thread_key": "幽灵线程",
                    "why": "不存在",
                    "evidence_refs": ["INBOX#999"],
                }],
                "pending_replies": [{
                    "thread_key": "部署评审",
                    "waiting_on_me": True,
                    "why": "请审批",
                    "evidence_refs": ["INBOX#7", "INBOX#999"],
                }],
                "sla_risks": [],
                "weekly_brief": {},
            })
            with mock.patch("twinbox_core.select.choose_candidates", side_effect=lambda ctx, *_a, **_k: (ctx["envelopes"], {})), \
                    mock.patch("twinbox_core.analyze.call_llm", return_value=llm):
                result = run_analysis(root)
            self.assertTrue(result["ok"])
            self.assertIn("幽灵线程", result["diagnostics"]["invalid_thread_keys"])
            self.assertIn("INBOX#999", result["diagnostics"]["invalid_evidence_refs"])
            import yaml
            pending = yaml.safe_load(
                (root / "runtime" / "validation" / "phase-4" / "pending-replies.yaml").read_text()
            )["pending_replies"]
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["evidence_refs"], ["INBOX#7"])
            self.assertEqual(pending[0]["evidence_basis"], "explicit")
            urgent = yaml.safe_load(
                (root / "runtime" / "validation" / "phase-4" / "daily-urgent.yaml").read_text()
            )["daily_urgent"]
            self.assertEqual(urgent, [])

    def test_owner_pending_without_refs_is_insufficient_watch(self) -> None:
        row = {
            "thread_key": "待审核",
            "queue_tags": ["pending"],
            "waiting_on_me": True,
            "evidence_basis": "insufficient",
            "why": "可能需要我回复",
        }
        self.assertEqual(project_item(row, None), "watch")

    def test_briefing_five_item_replay(self) -> None:
        """Anonymous 2-review + 3-watch shapes from the 9/18 briefing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            envelopes = [
                {
                    "subject": "请何诚审核方案",
                    "id": "11",
                    "folder": "INBOX",
                    "date": "2026-09-18T08:00:00+08:00",
                    "recipient_role": "cc_only",
                    "from_addr": "pm@example.com",
                },
                {
                    "subject": "请汪睿审核预算",
                    "id": "12",
                    "folder": "INBOX",
                    "date": "2026-09-18T08:10:00+08:00",
                    "recipient_role": "direct",
                    "from_addr": "pm@example.com",
                },
                {
                    "subject": "风险周报 13条 29条",
                    "id": "13",
                    "folder": "INBOX",
                    "date": "2026-09-18T08:20:00+08:00",
                    "recipient_role": "direct",
                },
                {
                    "subject": "CC点名他人跟进",
                    "id": "14",
                    "folder": "INBOX",
                    "date": "2026-09-18T08:30:00+08:00",
                    "recipient_role": "cc_only",
                },
                {
                    "subject": "知会：流程变更",
                    "id": "15",
                    "folder": "INBOX",
                    "date": "2026-09-18T08:40:00+08:00",
                    "recipient_role": "direct",
                },
            ]
            _ctx(root, envelopes)
            llm = json.dumps({
                "daily_urgent": [
                    {
                        "thread_key": "风险周报 13条 29条",
                        "why": "来源邮件报告13/29条预警",
                        "evidence_refs": ["INBOX#13"],
                    },
                ],
                "pending_replies": [
                    {
                        "thread_key": "请何诚审核方案",
                        "waiting_on_me": False,
                        "waiting_on": "何诚",
                        "why": "正文请何诚审核",
                        "evidence_refs": ["INBOX#11"],
                    },
                    {
                        "thread_key": "请汪睿审核预算",
                        "waiting_on_me": True,
                        "why": "可能需要我审",
                    },
                    {
                        "thread_key": "CC点名他人跟进",
                        "waiting_on_me": False,
                        "waiting_on": "李四",
                        "why": "请李四跟进",
                        "evidence_refs": ["INBOX#14"],
                    },
                    {
                        "thread_key": "知会：流程变更",
                        "waiting_on_me": True,
                        "why": "To了所以待我回复",
                    },
                ],
                "sla_risks": [],
                "weekly_brief": {},
            })
            with mock.patch("twinbox_core.select.choose_candidates", side_effect=lambda ctx, *_a, **_k: (ctx["envelopes"], {})), \
                    mock.patch("twinbox_core.analyze.call_llm", return_value=llm):
                result = run_analysis(root)
            self.assertTrue(result["ok"])
            import yaml
            pending = yaml.safe_load(
                (root / "runtime" / "validation" / "phase-4" / "pending-replies.yaml").read_text()
            )["pending_replies"]
            by_key = {row["thread_key"]: row for row in pending}
            he = by_key["请何诚审核方案"]
            self.assertEqual(he["action_target"], "何诚")
            self.assertEqual(he["evidence_basis"], "explicit")
            self.assertEqual(by_key["请汪睿审核预算"]["evidence_basis"], "insufficient")
            self.assertEqual(by_key["cc点名他人跟进"]["action_target"], "李四")
            self.assertEqual(by_key["知会：流程变更"]["evidence_basis"], "insufficient")
            raw_dir = root / "runtime" / "validation" / "phase-1" / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "envelopes-merged.json").write_text(json.dumps(envelopes), encoding="utf-8")
            payload, _ = write_activity_pulse(root)
            todo = {row["thread_key"]: row for row in payload.get("needs_attention") or []}
            self.assertEqual(todo["请汪睿审核预算"].get("projection"), "watch")
            self.assertEqual(todo["知会：流程变更"].get("projection"), "watch")
            self.assertEqual(todo["请何诚审核方案"].get("latest_recipient_role"), "cc_only")
            self.assertEqual(todo["请汪睿审核预算"].get("latest_recipient_role"), "direct")
            self.assertNotIn("evidence_refs", {
                k for row in (payload.get("projections") or {}).get("watch") or [] for k in row
            })


if __name__ == "__main__":
    unittest.main()
