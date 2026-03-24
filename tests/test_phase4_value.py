from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from twinbox_core.phase4_value import merge_phase4_outputs


class Phase4ValueTest(unittest.TestCase):
    def test_merge_writes_phase4_outputs(self) -> None:
        urgent_pending = {
            "daily_urgent": [
                {
                    "thread_key": "资源申请",
                    "flow": "LF1",
                    "stage": "LF1-S2",
                    "urgency_score": 88,
                    "why": "等待审批",
                    "action_hint": "今天跟进审批人",
                    "owner": "owner@example.com",
                    "waiting_on": "approver@example.com",
                    "evidence_source": "mail_evidence",
                }
            ],
            "pending_replies": [
                {
                    "thread_key": "资源申请",
                    "flow": "LF1",
                    "waiting_on_me": True,
                    "why": "需要确认资源",
                    "suggested_action": "回复审批意见",
                    "evidence_source": "mail_evidence",
                }
            ],
        }
        risks = {
            "sla_risks": [
                {
                    "thread_key": "部署失败",
                    "flow": "LF2",
                    "risk_type": "deployment_failure",
                    "risk_description": "部署失败待处理",
                    "days_since_last_activity": 2,
                    "suggested_action": "安排复盘",
                }
            ]
        }
        brief = {
            "weekly_brief": {
                "period": "2026-03-13~2026-03-20",
                "total_threads_in_window": 12,
                "flow_summary": [{"flow": "LF1", "name": "资源申请", "count": 5, "highlight": "审批积压"}],
                "top_actions": ["清理审批积压"],
                "rhythm_observation": "周中最忙。",
            }
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "runtime/validation/phase-4"
            doc_dir = root / "docs/validation"
            output_dir.mkdir(parents=True)
            doc_dir.mkdir(parents=True)

            (output_dir / "urgent-pending-raw.json").write_text(json.dumps(urgent_pending, ensure_ascii=False), encoding="utf-8")
            (output_dir / "sla-risks-raw.json").write_text(json.dumps(risks, ensure_ascii=False), encoding="utf-8")
            (output_dir / "weekly-brief-raw.json").write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")

            merge_phase4_outputs(
                output_dir=output_dir,
                doc_dir=doc_dir,
                env_file=None,
                model_override="test-model",
            )

            self.assertIn("资源申请", (output_dir / "daily-urgent.yaml").read_text(encoding="utf-8"))
            self.assertIn("deployment_failure", (output_dir / "sla-risks.yaml").read_text(encoding="utf-8"))
            self.assertIn("Top Actions", (output_dir / "weekly-brief.md").read_text(encoding="utf-8"))
            self.assertIn("Phase 4 Report", (doc_dir / "phase-4-report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
