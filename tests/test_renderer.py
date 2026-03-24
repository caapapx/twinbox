from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from twinbox_core.renderer import render_phase2_outputs, render_phase3_outputs, render_phase4_outputs


class RendererTest(unittest.TestCase):
    def test_render_phase2_outputs_writes_artifacts(self) -> None:
        context = {
            "mailbox_summary": {"total_envelopes": 10, "internal_external": {"internal": 7, "external": 3, "unknown": 0}},
            "intent_distribution": [{"key": "release", "count": 4}],
            "top_contacts": [{"key": "alice@example.com", "count": 3}],
            "top_domains": [{"key": "example.com", "count": 8}],
        }
        response = {
            "persona_hypotheses": [{"id": "P1", "type": "role", "hypothesis": "负责交付", "confidence": 0.9, "evidence": ["release(4)"]}],
            "business_hypotheses": [{"id": "B1", "hypothesis": "项目交付驱动", "confidence": 0.8, "evidence": ["example.com(8)"], "ai_entry_points": ["生成摘要"]}],
            "confirmation_questions": ["是否负责审批？"],
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            render_phase2_outputs(
                output_dir=root / "phase-2",
                doc_dir=root / "docs",
                diagram_dir=root / "docs/diagrams",
                context=context,
                response=response,
                model_name="test-model",
            )
            self.assertIn("负责交付", (root / "phase-2/persona-hypotheses.yaml").read_text(encoding="utf-8"))
            self.assertIn("graph TD", (root / "docs/diagrams/phase-2-relationship-map.mmd").read_text(encoding="utf-8"))

    def test_render_phase3_outputs_writes_artifacts(self) -> None:
        response = {
            "lifecycle_flows": [{"id": "LF1", "name": "资源流", "description": "desc", "evidence_threads": ["资源申请"], "stages": [{"id": "LF1-S1", "name": "申请", "entry_signal": "收到", "exit_signal": "审批", "owner_guess": "A", "waiting_on": "B", "due_hint": "今天", "risk_signal": "卡住", "ai_action": "remind"}]}],
            "thread_stage_samples": [{"thread_key": "资源申请", "flow": "LF1", "inferred_stage": "LF1-S1", "confidence": 0.9, "evidence": "主题匹配"}],
            "phase4_recommendations": ["优先 LF1"],
            "policy_suggestions": ["加规则"],
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            render_phase3_outputs(
                output_dir=root / "phase-3",
                doc_dir=root / "docs",
                diagram_dir=root / "docs/diagrams",
                response=response,
                model_name="test-model",
            )
            self.assertIn("资源流", (root / "phase-3/lifecycle-model.yaml").read_text(encoding="utf-8"))
            self.assertIn("stateDiagram-v2", (root / "docs/diagrams/phase-3-thread-state-machine.mmd").read_text(encoding="utf-8"))

    def test_render_phase4_outputs_writes_artifacts(self) -> None:
        response = {
            "daily_urgent": [{"thread_key": "资源申请", "flow": "LF1", "stage": "LF1-S2", "urgency_score": 80, "why": "待审批", "action_hint": "跟进", "owner": "alice", "waiting_on": "bob", "evidence_source": "mail_evidence"}],
            "pending_replies": [{"thread_key": "资源申请", "flow": "LF1", "waiting_on_me": True, "why": "需回复", "suggested_action": "答复", "evidence_source": "mail_evidence"}],
            "sla_risks": [{"thread_key": "部署失败", "flow": "LF2", "risk_type": "deployment_failure", "risk_description": "失败", "days_since_last_activity": 1, "suggested_action": "复盘"}],
            "weekly_brief": {"period": "本周", "total_threads_in_window": 5, "flow_summary": [{"flow": "LF1", "name": "资源流", "count": 3, "highlight": "积压"}], "top_actions": ["处理积压"], "rhythm_observation": "周中忙"},
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            render_phase4_outputs(
                output_dir=root / "phase-4",
                doc_dir=root / "docs",
                response=response,
                method="llm",
                model_name="test-model",
            )
            self.assertIn("资源申请", (root / "phase-4/daily-urgent.yaml").read_text(encoding="utf-8"))
            self.assertIn("Weekly Brief", (root / "phase-4/weekly-brief.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
