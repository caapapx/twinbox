# Implementation Plan: Policy-Governed Workflow Automation (dry-run increment)

**Branch**: `master` (spec dir `006-policy-governed-workflow-automation`) | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-policy-governed-workflow-automation/spec.md`

## Summary

**本增量 dry-run**：策略声明在 pack；提案引擎（源自 archive ActionCard）；审计 `runtime/audit/actions.jsonl`；确认卡片 payload 按 agent-os 卡片回调形状输出。Twinbox 不接飞书 SDK、不接 SMTP、不写真实邮箱。FR-007 只读默认保持。完整自动执行是后续增量。

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `003` pack `action_policy`；无飞书/SMTP SDK

**Storage**: `runtime/audit/actions.jsonl`；本地提案状态 `runtime/actions/proposals.json`

**Testing**: pytest；策略外 0 提案；幂等键重放不写第二行成功副作用（dry-run 下「副作用」= 提案记录）

**Target Platform**: 本机 MCP；卡片由 agent-os 8090 投递（本增量只产 payload）

**Project Type**: library + MCP tool server

**Performance Goals**: 提案扫描跟在 pulse 之后，不额外打 IMAP

**Constraints**: 无 SMTP；无写邮箱；模型置信度不能单独授权；通道失败不得当确认

**Scale/Scope**: 读工具 `twinbox_action_proposals` + 本地审 `twinbox_action_review`

## Constitution Check

- **I**: 本增量无邮箱副作用；提案/审计/本地 review 是 local-only。✅
- **II**: 卡片 payload 用引用 + 有界摘要，无全文。✅
- **IV**: 新工具 additive；九工具保留。✅
- **ADR-002 / ADR-003**: 策略未命中不执行；通道委托 agent-os。✅

## Project Structure

```text
twinbox_core/actions.py
tests/test_actions.py
runtime/audit/actions.jsonl   # state root, not tracked
```

## Phase 1: Design

提案字段：`proposal_id`、`idempotency_key`、`policy_id`/`policy_version`、`action_type`、`target_scope`、`thread_key`、`evidence_refs`、`card_payload`、`status`（proposed/confirmed/rejected/expired）。

`twinbox_action_review` 只改本地状态。确认卡片不在 Twinbox 内投递。策略外扫描结果必须是空列表，不得「建议用户手动转发」冒充策略命中。
