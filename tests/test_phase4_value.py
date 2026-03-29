from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pytest

from twinbox_core.phase4_value import (
    PHASE4_MAILBOX_USER_PREFIX,
    URGENT_PROMPT,
    Phase4RunConfig,
    _apply_recipient_role_weights,
    _call_with_prompt,
    _ensure_material_summary,
    derive_material_summary,
    merge_phase4_outputs,
    phase4_brief_system_prompt,
    phase4_urgent_system_prompt,
    run_single,
    run_subtask,
)


class Phase4ValueTest(unittest.TestCase):
    def test_urgent_prompt_excludes_recipient_role_scoring_rule(self) -> None:
        self.assertNotIn("recipient_role", URGENT_PROMPT)

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
            self.assertNotIn("⚠️ 你不是主要收件人", cc_pending["why"])
            self.assertNotIn("recipient_role", direct_pending)

    def test_apply_recipient_role_weights_downweights_group_only_threads(self) -> None:
        response = {
            "daily_urgent": [
                {"thread_key": "group-thread", "urgency_score": 90, "why": "通过邮件组收到"},
            ],
            "pending_replies": [
                {"thread_key": "group-thread", "why": "请确认是否需要跟进", "waiting_on_me": True},
            ],
        }
        context = {
            "top_threads": [
                {"thread_key": "group-thread", "recipient_role": "group_only"},
            ]
        }

        with tempfile.TemporaryDirectory() as tmp:
            context_path = Path(tmp) / "context-pack.json"
            context_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")

            weighted = _apply_recipient_role_weights(response, context_path)

            group_urgent = weighted["daily_urgent"][0]
            group_pending = weighted["pending_replies"][0]

            self.assertEqual(group_urgent["urgency_score"], 36)  # 90 * 0.4
            self.assertEqual(group_urgent["recipient_role"], "group_only")
            self.assertEqual(group_pending["recipient_role"], "group_only")
            self.assertNotIn("⚠️ 你不是主要收件人", group_pending["why"])

    def test_apply_recipient_role_weights_reads_phase4_threads_key(self) -> None:
        response = {
            "daily_urgent": [
                {"thread_key": "cc-thread", "urgency_score": 50, "why": "x"},
            ],
            "pending_replies": [],
        }
        context = {
            "threads": [
                {"thread_key": "cc-thread", "recipient_role": "cc_only"},
            ]
        }
        with tempfile.TemporaryDirectory() as tmp:
            context_path = Path(tmp) / "context-pack.json"
            context_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
            weighted = _apply_recipient_role_weights(response, context_path)
            self.assertEqual(weighted["daily_urgent"][0]["urgency_score"], 30)
            self.assertEqual(weighted["daily_urgent"][0]["recipient_role"], "cc_only")

    def test_apply_recipient_role_weights_falls_back_to_phase3_context_pack(self) -> None:
        response = {
            "daily_urgent": [
                {"thread_key": "group-thread", "urgency_score": 90, "why": "通过邮件组收到"},
            ],
            "pending_replies": [
                {"thread_key": "group-thread", "why": "请确认是否需要跟进", "waiting_on_me": True},
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase4_context_path = root / "runtime/validation/phase-4/context-pack.json"
            phase3_context_path = root / "runtime/validation/phase-3/context-pack.json"
            phase4_context_path.parent.mkdir(parents=True, exist_ok=True)
            phase3_context_path.parent.mkdir(parents=True, exist_ok=True)

            phase4_context_path.write_text(json.dumps({"thread_contexts": []}, ensure_ascii=False), encoding="utf-8")
            phase3_context_path.write_text(
                json.dumps(
                    {
                        "top_threads": [
                            {"thread_key": "group-thread", "recipient_role": "group_only"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            weighted = _apply_recipient_role_weights(response, phase4_context_path)

            self.assertEqual(weighted["daily_urgent"][0]["recipient_role"], "group_only")
            self.assertEqual(weighted["pending_replies"][0]["recipient_role"], "group_only")


def _minimal_full_phase4_llm_json() -> str:
    return json.dumps(
        {
            "daily_urgent": [
                {
                    "thread_key": "cc-thread",
                    "flow": "LF1",
                    "stage": "S1",
                    "urgency_score": 100,
                    "reason_code": "waiting_on_me",
                    "why": "需要处理",
                    "action_hint": "回复",
                    "owner": "o",
                    "waiting_on": "w",
                    "evidence_source": "mail_evidence",
                }
            ],
            "pending_replies": [],
            "sla_risks": [],
            "weekly_brief": {
                "period": "p",
                "total_threads_in_window": 0,
                "action_now": [],
                "backlog": [],
                "important_changes": [],
                "flow_summary": [],
                "top_actions": [],
                "rhythm_observation": "r",
            },
        },
        ensure_ascii=False,
    )


def test_run_single_applies_recipient_role_weights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    context = {
        "threads": [{"thread_key": "cc-thread", "recipient_role": "cc_only"}],
        "human_context": {},
    }
    ctx_path = tmp_path / "context-pack.json"
    ctx_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "phase-4-out"
    doc = tmp_path / "docs"

    monkeypatch.setattr("twinbox_core.phase4_value.call_llm", lambda *a, **k: _minimal_full_phase4_llm_json())
    monkeypatch.setattr(
        "twinbox_core.phase4_value.resolve_backend",
        lambda **k: SimpleNamespace(backend="stub", model="stub-model"),
    )
    monkeypatch.setattr("twinbox_core.phase4_value.render_phase4_outputs", lambda **k: None)

    cfg = Phase4RunConfig(
        context_path=ctx_path,
        output_dir=out,
        doc_dir=doc,
        dry_run=False,
        env_file=None,
        model_override="stub-model",
        max_tokens=1024,
    )
    result = run_single(cfg)
    assert result["daily_urgent"][0]["urgency_score"] == 60
    assert result["daily_urgent"][0]["recipient_role"] == "cc_only"


def test_apply_recipient_role_weights_can_disable_score_downweight_from_config(
    tmp_path: Path,
) -> None:
    response = {
        "daily_urgent": [
            {"thread_key": "cc-thread", "urgency_score": 90, "why": "需要关注"},
        ],
        "pending_replies": [
            {"thread_key": "cc-thread", "why": "请确认", "waiting_on_me": True},
        ],
    }
    context = {
        "top_threads": [
            {"thread_key": "cc-thread", "recipient_role": "cc_only"},
        ]
    }
    context_path = tmp_path / "runtime" / "validation" / "phase-4" / "context-pack.json"
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "twinbox.json").write_text(
        json.dumps(
            {
                "version": 1,
                "preferences": {
                    "cc_downweight": {
                        "enabled": False,
                        "weights": {"cc_only": 0.6, "indirect": 0.6, "group_only": 0.4},
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    weighted = _apply_recipient_role_weights(response, context_path, state_root=tmp_path)

    assert weighted["daily_urgent"][0]["urgency_score"] == 90
    assert weighted["daily_urgent"][0]["recipient_role"] == "cc_only"
    assert weighted["pending_replies"][0]["recipient_role"] == "cc_only"


def test_run_subtask_urgent_applies_recipient_role_weights(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    context = {
        "threads": [{"thread_key": "cc-thread", "recipient_role": "cc_only"}],
        "human_context": {},
    }
    ctx_path = tmp_path / "context-pack.json"
    ctx_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "phase-4-out"
    out.mkdir(parents=True)

    urgent_json = json.dumps(
        {
            "daily_urgent": [
                {
                    "thread_key": "cc-thread",
                    "flow": "LF1",
                    "stage": "S1",
                    "urgency_score": 100,
                    "reason_code": "waiting_on_me",
                    "why": "需要处理",
                    "action_hint": "回复",
                    "owner": "o",
                    "waiting_on": "w",
                    "evidence_source": "mail_evidence",
                }
            ],
            "pending_replies": [],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr("twinbox_core.phase4_value.call_llm", lambda *a, **k: urgent_json)
    monkeypatch.setattr(
        "twinbox_core.phase4_value.resolve_backend",
        lambda **k: SimpleNamespace(backend="stub", model="stub-model"),
    )

    result = run_subtask(
        kind="urgent",
        context_path=ctx_path,
        output_dir=out,
        env_file=None,
        model_override="stub-model",
    )
    assert result["daily_urgent"][0]["urgency_score"] == 60
    assert result["daily_urgent"][0]["recipient_role"] == "cc_only"


def test_run_subtask_urgent_writes_action_candidates_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = {
        "threads": [{"thread_key": "cc-thread", "recipient_role": "cc_only"}],
        "human_context": {},
    }
    ctx_path = tmp_path / "context-pack.json"
    ctx_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "phase-4-out"
    out.mkdir(parents=True)

    urgent_json = json.dumps(
        {
            "daily_urgent": [
                {
                    "thread_key": "cc-thread",
                    "flow": "LF1",
                    "stage": "S1",
                    "urgency_score": 100,
                    "reason_code": "waiting_on_me",
                    "why": "需要处理",
                    "action_hint": "回复",
                    "owner": "o",
                    "waiting_on": "w",
                    "evidence_source": "mail_evidence",
                }
            ],
            "pending_replies": [
                {
                    "thread_key": "pending-only",
                    "flow": "LF2",
                    "waiting_on_me": True,
                    "reason_code": "approval_needed",
                    "why": "等你确认",
                    "suggested_action": "批准",
                    "evidence_source": "mail_evidence",
                }
            ],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr("twinbox_core.phase4_value.call_llm", lambda *a, **k: urgent_json)
    monkeypatch.setattr(
        "twinbox_core.phase4_value.resolve_backend",
        lambda **k: SimpleNamespace(backend="stub", model="stub-model"),
    )

    run_subtask(
        kind="urgent",
        context_path=ctx_path,
        output_dir=out,
        env_file=None,
        model_override="stub-model",
    )

    payload = json.loads((out / "action-candidates.json").read_text(encoding="utf-8"))
    assert [item["thread_key"] for item in payload["action_candidates"]] == ["cc-thread", "pending-only"]
    assert payload["action_candidates"][0] == {
        "thread_key": "cc-thread",
        "urgency_score": 60,
        "reason_code": "waiting_on_me",
        "why": "需要处理",
        "action_hint": "回复",
    }
    assert payload["action_candidates"][1] == {
        "thread_key": "pending-only",
        "urgency_score": 0,
        "reason_code": "approval_needed",
        "why": "等你确认",
        "action_hint": "批准",
    }


def test_run_subtask_brief_includes_action_candidates_in_user_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}
    context = {"threads": [], "human_context": {}}
    ctx_path = tmp_path / "context-pack.json"
    ctx_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "phase-4-out"
    out.mkdir(parents=True)
    (out / "action-candidates.json").write_text(
        json.dumps(
            {
                "action_candidates": [
                    {
                        "thread_key": "thread-A",
                        "urgency_score": 88,
                        "reason_code": "waiting_on_me",
                        "why": "今天必须回复",
                        "action_hint": "回复客户",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    def fake_llm(
        prompt: str,
        max_tokens: int = 4096,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> str:
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt or ""
        return json.dumps(
            {
                "weekly_brief": {
                    "period": "p",
                    "total_threads_in_window": 0,
                    "action_now": [],
                    "backlog": [],
                    "important_changes": [],
                    "flow_summary": [],
                    "top_actions": [],
                    "rhythm_observation": "r",
                }
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("twinbox_core.phase4_value.call_llm", fake_llm)
    monkeypatch.setattr(
        "twinbox_core.phase4_value.resolve_backend",
        lambda **k: SimpleNamespace(backend="stub", model="stub-model"),
    )

    run_subtask(
        kind="brief",
        context_path=ctx_path,
        output_dir=out,
        env_file=None,
        model_override="stub-model",
    )

    assert "shared action candidate list" in captured["system_prompt"].lower()
    assert "## Shared action candidates:" in captured["prompt"]
    assert "- thread-A | score=88 | reason=waiting_on_me | why=今天必须回复 | action=回复客户" in captured["prompt"]


def test_run_subtask_brief_aligns_weekly_action_fields_with_candidate_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = {"threads": [], "human_context": {}}
    ctx_path = tmp_path / "context-pack.json"
    ctx_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "phase-4-out"
    out.mkdir(parents=True)
    (out / "action-candidates.json").write_text(
        json.dumps(
            {
                "action_candidates": [
                    {
                        "thread_key": "direct-thread",
                        "urgency_score": 80,
                        "reason_code": "waiting_on_me",
                        "why": "主收件线程",
                        "action_hint": "先回复客户A",
                    },
                    {
                        "thread_key": "cc-thread",
                        "urgency_score": 54,
                        "reason_code": "monitor_only",
                        "why": "抄送线程",
                        "action_hint": "再关注法务进展",
                    },
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "twinbox_core.phase4_value.call_llm",
        lambda *a, **k: json.dumps(
            {
                "weekly_brief": {
                    "period": "p",
                    "total_threads_in_window": 0,
                    "action_now": [
                        {"thread_key": "cc-thread", "flow": "legal", "why": "先看抄送", "action": "关注法务进展"},
                        {"thread_key": "direct-thread", "flow": "sales", "why": "客户在等", "action": "回复客户A"},
                    ],
                    "backlog": [],
                    "important_changes": [
                        {"thread_key": "cc-thread", "change": "法务已更新", "impact": "仍需关注"}
                    ],
                    "flow_summary": [],
                    "top_actions": ["关注法务进展", "回复客户A"],
                    "rhythm_observation": "r",
                }
            },
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(
        "twinbox_core.phase4_value.resolve_backend",
        lambda **k: SimpleNamespace(backend="stub", model="stub-model"),
    )

    result = run_subtask(
        kind="brief",
        context_path=ctx_path,
        output_dir=out,
        env_file=None,
        model_override="stub-model",
    )

    weekly = result["weekly_brief"]
    assert [item["thread_key"] for item in weekly["action_now"]] == ["direct-thread", "cc-thread"]
    assert weekly["top_actions"] == ["回复客户A", "关注法务进展"]
    assert weekly["important_changes"] == [{"thread_key": "cc-thread", "change": "法务已更新", "impact": "仍需关注"}]


def test_run_subtask_urgent_writes_daily_ledger_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = {"threads": [], "human_context": {}}
    ctx_path = tmp_path / "context-pack.json"
    ctx_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "phase-4-out"
    out.mkdir(parents=True)

    monkeypatch.setattr(
        "twinbox_core.phase4_value.call_llm",
        lambda *a, **k: json.dumps(
            {
                "daily_urgent": [
                    {
                        "thread_key": "invoice-issue",
                        "urgency_score": 88,
                        "reason_code": "waiting_on_me",
                        "why": "需要先修发票异常",
                        "action_hint": "联系供应商",
                        "stage": "open",
                    }
                ],
                "pending_replies": [],
            },
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(
        "twinbox_core.phase4_value.resolve_backend",
        lambda **k: SimpleNamespace(backend="stub", model="stub-model"),
    )

    run_subtask(
        kind="urgent",
        context_path=ctx_path,
        output_dir=out,
        env_file=None,
        model_override="stub-model",
    )

    ledger_files = sorted((out / "daily-ledger").glob("*.json"))
    assert len(ledger_files) == 1
    payload = json.loads(ledger_files[0].read_text(encoding="utf-8"))
    assert payload["threads"] == [
        {
            "thread_key": "invoice-issue",
            "state": "open",
            "urgency_score": 88,
            "reason_code": "waiting_on_me",
            "why": "需要先修发票异常",
            "action_hint": "联系供应商",
            "source": "daily_urgent",
        }
    ]


def test_merge_phase4_outputs_replays_daily_ledger_history_into_weekly_brief() -> None:
    urgent_pending = {"daily_urgent": [], "pending_replies": []}
    risks = {"sla_risks": []}
    brief = {
        "weekly_brief": {
            "period": "2026-03-18 ~ 2026-03-24",
            "total_threads_in_window": 12,
            "flow_summary": [],
            "top_actions": [],
            "action_now": [],
            "backlog": [],
            "important_changes": [],
            "rhythm_observation": "周中最忙。",
        }
    }

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        output_dir = root / "runtime/validation/phase-4"
        doc_dir = root / "docs/validation"
        ledger_dir = output_dir / "daily-ledger"
        ledger_dir.mkdir(parents=True)
        doc_dir.mkdir(parents=True)

        (output_dir / "urgent-pending-raw.json").write_text(json.dumps(urgent_pending, ensure_ascii=False), encoding="utf-8")
        (output_dir / "sla-risks-raw.json").write_text(json.dumps(risks, ensure_ascii=False), encoding="utf-8")
        (output_dir / "weekly-brief-raw.json").write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")
        (ledger_dir / "20260318T090000+0800.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-18T09:00:00+08:00",
                    "threads": [
                        {
                            "thread_key": "invoice-issue",
                            "state": "open",
                            "urgency_score": 88,
                            "reason_code": "waiting_on_me",
                            "why": "需要先修发票异常",
                            "action_hint": "联系供应商",
                            "source": "daily_urgent",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (ledger_dir / "20260310T090000+0800.json").write_text(
            json.dumps(
                {
                    "generated_at": "2026-03-10T09:00:00+08:00",
                    "threads": [
                        {
                            "thread_key": "old-thread",
                            "state": "open",
                            "urgency_score": 90,
                            "reason_code": "waiting_on_me",
                            "why": "超出本周范围",
                            "action_hint": "忽略",
                            "source": "daily_urgent",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        merge_phase4_outputs(
            output_dir=output_dir,
            doc_dir=doc_dir,
            env_file=None,
            model_override="test-model",
        )

        updated = json.loads((output_dir / "weekly-brief-raw.json").read_text(encoding="utf-8"))
        assert updated["weekly_brief"]["important_changes"] == [
            {
                "thread_key": "invoice-issue",
                "change": "本周早些时候进入今日行动面: 需要先修发票异常",
                "impact": "当前已退出当前行动面，周报保留该线程的本周轨迹",
            }
        ]


def test_call_with_prompt_passes_system_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_llm(
        prompt: str,
        max_tokens: int = 4096,
        system_prompt: str | None = None,
        **kwargs: object,
    ) -> str:
        captured["system_prompt"] = system_prompt
        captured["user_head"] = prompt[:80]
        return '{"daily_urgent":[],"pending_replies":[]}'

    monkeypatch.setattr("twinbox_core.phase4_value.call_llm", fake_llm)
    ctx_path = tmp_path / "ctx.json"
    ctx_path.write_text('{"threads":[]}', encoding="utf-8")

    _call_with_prompt(
        system_prompt=phase4_urgent_system_prompt(),
        user_prefix=PHASE4_MAILBOX_USER_PREFIX,
        context_path=ctx_path,
        env_file=None,
        model_override=None,
        max_tokens=256,
    )

    sys_p = captured["system_prompt"]
    assert isinstance(sys_p, str) and len(sys_p) > 0
    urgent = phase4_urgent_system_prompt()
    brief = phase4_brief_system_prompt()
    assert "calibration_notes" in urgent
    assert "template_hint" not in urgent
    assert "template_hint" in brief
    assert "0.85" not in urgent
    assert "Confidence must reflect actual certainty" not in urgent


def test_dry_run_sees_filtered_threads(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    context = {
        "threads": [
            {"thread_key": "keep-me", "recipient_role": "direct", "skip_phase4": False},
            {"thread_key": "skip-me", "recipient_role": "direct", "skip_phase4": True},
        ],
        "human_context": {},
    }
    ctx_path = tmp_path / "context-pack.json"
    ctx_path.write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
    cfg = Phase4RunConfig(
        context_path=ctx_path,
        output_dir=tmp_path / "out",
        doc_dir=tmp_path / "doc",
        dry_run=True,
        env_file=None,
        model_override=None,
        max_tokens=1024,
    )
    run_single(cfg)
    captured = capsys.readouterr().out
    assert "threads after filter: 1" in captured


if __name__ == "__main__":
    unittest.main()
