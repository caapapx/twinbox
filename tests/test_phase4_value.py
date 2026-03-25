from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from twinbox_core.phase4_value import (
    _apply_recipient_role_weights,
    _ensure_material_summary,
    derive_material_summary,
    merge_phase4_outputs,
)


class Phase4ValueTest(unittest.TestCase):
    def test_derive_material_summary_covers_all_columns(self) -> None:
        context = {
            "human_context": {
                "material_extracts_notes": """
<!-- weekly-deployment-ledger-sample_md.extracted.md -->

# 自上传文本: weekly-deployment-ledger-sample.md

# 周部署台账（合成样例，用于干预评测）

本周：2026-03-17 至 2026-03-23

| 资源/版本 | 产品 | 出库日 | 部署起止 | 结果 | 是否达预期 | 问题反馈 |
|-----------|------|--------|----------|------|------------|----------|
| 项目A-中间件-x.y | 产品甲 | 2026-03-18 | 03-18 ~ 03-19 | 一次成功 | 是 | 无 |
| 项目B-检索-z.w | 产品乙 | 2026-03-19 | 03-19 ~ 03-22 | 一次成功 | 部分 | 首批节点 RAID 异常，检索未跑满 GPU |
"""
            }
        }

        summary = derive_material_summary(context)

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["table_title"], "周部署台账（合成样例，用于干预评测）")
        self.assertTrue(summary["is_synthetic"])
        self.assertEqual(summary["row_count"], 2)
        self.assertEqual(
            summary["table_headers"],
            ["资源/版本", "产品", "出库日", "部署起止", "结果", "是否达预期", "问题反馈"],
        )
        column_stats = {item["column"]: item["summary"] for item in summary["column_stats"]}
        self.assertIn("一次成功=2", column_stats["结果"])
        self.assertIn("是=1", column_stats["是否达预期"])
        self.assertIn("部分=1", column_stats["是否达预期"])
        self.assertIn("原始区间", column_stats["部署起止"])
        self.assertIn("RAID 异常", summary["open_risks"][0])
        self.assertIn("不得直接作为本周事实", summary["notes"])

    def test_ensure_material_summary_overrides_llm_material_stats_and_filters_synthetic_actions(self) -> None:
        context = {
            "human_context": {
                "material_extracts_notes": """
<!-- weekly-deployment-ledger-sample_md.extracted.md -->

# 自上传文本: weekly-deployment-ledger-sample.md

# 周部署台账（合成样例，用于干预评测）

> 非真实数据

| 资源/版本 | 产品 | 部署起止 | 结果 |
|-----------|------|----------|------|
| 项目B-检索-z.w | 产品乙 | 03-19 ~ 03-22 | 一次成功 |
"""
            }
        }
        response = {
            "weekly_brief": {
                "material_summary": {
                    "column_stats": [{"column": "部署起止", "summary": "部署周期1-4天不等"}],
                },
                "top_actions": ["继续跟踪项目B检索版本GPU未跑满风险"],
            }
        }

        merged = _ensure_material_summary(response, context=context)
        material_summary = merged["weekly_brief"]["material_summary"]
        column_stats = {item["column"]: item["summary"] for item in material_summary["column_stats"]}

        self.assertEqual(merged["weekly_brief"]["top_actions"], [])
        self.assertIn("原始区间", column_stats["部署起止"])
        self.assertTrue(material_summary["is_synthetic"])

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

    def test_apply_recipient_role_weights_downweights_cc_only_threads(self) -> None:
        response = {
            "daily_urgent": [
                {"thread_key": "cc-thread", "urgency_score": 90, "why": "需要关注"},
                {"thread_key": "direct-thread", "urgency_score": 80, "why": "直接收件"},
            ],
            "pending_replies": [
                {"thread_key": "cc-thread", "why": "请确认", "waiting_on_me": True},
                {"thread_key": "direct-thread", "why": "请回复", "waiting_on_me": True},
            ],
        }
        context = {
            "top_threads": [
                {"thread_key": "cc-thread", "recipient_role": "cc_only"},
                {"thread_key": "direct-thread", "recipient_role": "direct"},
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            context_path = Path(tmp) / "context-pack.json"
            context_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")

            weighted = _apply_recipient_role_weights(response, context_path)

            cc_urgent = next(item for item in weighted["daily_urgent"] if item["thread_key"] == "cc-thread")
            direct_urgent = next(item for item in weighted["daily_urgent"] if item["thread_key"] == "direct-thread")
            cc_pending = next(item for item in weighted["pending_replies"] if item["thread_key"] == "cc-thread")
            direct_pending = next(item for item in weighted["pending_replies"] if item["thread_key"] == "direct-thread")

            self.assertEqual(cc_urgent["urgency_score"], 54)
            self.assertEqual(cc_urgent["recipient_role"], "cc_only")
            self.assertEqual(direct_urgent["urgency_score"], 80)
            self.assertNotIn("recipient_role", direct_urgent)
            self.assertEqual(cc_pending["recipient_role"], "cc_only")
            self.assertIn("⚠️ 你仅在抄送列表中", cc_pending["why"])
            self.assertNotIn("recipient_role", direct_pending)


if __name__ == "__main__":
    unittest.main()
