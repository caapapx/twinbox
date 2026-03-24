from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from twinbox_core.llm import BackendConfig
from twinbox_core.phase3_lifecycle import Phase3RunConfig, run_phase3_lifecycle


class Phase3LifecycleTest(unittest.TestCase):
    def test_run_writes_phase3_outputs(self) -> None:
        context = {
            "mailbox_summary": {"total_envelopes": 20, "total_threads": 5},
            "top_threads": [{"thread_key": "资源申请", "count": 4}],
        }
        llm_response = {
            "lifecycle_flows": [
                {
                    "id": "LF1",
                    "name": "资源申请审批流",
                    "description": "从提交到审批结束。",
                    "evidence_threads": ["资源申请(4)"],
                    "stages": [
                        {
                            "id": "LF1-S1",
                            "name": "提交申请",
                            "entry_signal": "收到申请邮件",
                            "exit_signal": "提交审批",
                            "owner_guess": "申请人",
                            "waiting_on": "审批人",
                            "due_hint": "当天",
                            "risk_signal": "无人响应",
                            "ai_action": "remind",
                        }
                    ],
                }
            ],
            "thread_stage_samples": [
                {
                    "thread_key": "资源申请",
                    "flow": "LF1",
                    "inferred_stage": "LF1-S1",
                    "stage_name": "提交申请",
                    "evidence": "主题含资源申请",
                    "confidence": 0.88,
                    "ai_action": "remind",
                }
            ],
            "phase4_recommendations": ["优先覆盖 LF1"],
            "policy_suggestions": ["增加审批提醒规则"],
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context_path = root / "context-pack.json"
            output_dir = root / "runtime/validation/phase-3"
            doc_dir = root / "docs/validation"
            diagram_dir = doc_dir / "diagrams"
            context_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")

            with mock.patch(
                "twinbox_core.phase3_lifecycle.resolve_backend",
                return_value=BackendConfig("openai", "test-model", "https://example.com", "key", 10, 1),
            ), mock.patch(
                "twinbox_core.phase3_lifecycle.call_llm",
                return_value=json.dumps(llm_response, ensure_ascii=False),
            ):
                run_phase3_lifecycle(
                    Phase3RunConfig(
                        context_path=context_path,
                        output_dir=output_dir,
                        doc_dir=doc_dir,
                        diagram_dir=diagram_dir,
                        dry_run=False,
                        env_file=None,
                        model_override=None,
                    )
                )

            self.assertIn("资源申请审批流", (output_dir / "lifecycle-model.yaml").read_text(encoding="utf-8"))
            self.assertIn("LF1-S1", (output_dir / "thread-stage-samples.json").read_text(encoding="utf-8"))
            self.assertIn("Phase 3 Report", (doc_dir / "phase-3-report.md").read_text(encoding="utf-8"))
            self.assertIn("graph TD", (diagram_dir / "phase-3-lifecycle-overview.mmd").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
