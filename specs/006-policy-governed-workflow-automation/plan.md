# Implementation Plan: Policy-Governed Workflow Automation (dry-run increment)

**Branch**: `master` (spec dir `006-policy-governed-workflow-automation`) | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-policy-governed-workflow-automation/spec.md`

## Summary

**本增量 dry-run**：策略声明在 pack；提案引擎（源自 archive ActionCard）；审计 `runtime/audit/actions.jsonl`；确认卡片 payload 按宿主 webhook 回调形状输出。Twinbox 不接飞书 SDK、不接 SMTP、不写真实邮箱。FR-007 只读默认保持。完整自动执行是后续增量。

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `003` pack `action_policy`；无飞书/SMTP SDK

**Storage**: `runtime/audit/actions.jsonl`；本地提案状态 `runtime/actions/proposals.json`

**Testing**: pytest；策略外 0 提案；幂等键重放不写第二行成功副作用（dry-run 下「副作用」= 提案记录）

**Target Platform**: 本机 MCP；卡片由宿主 webhook 投递（本增量只产 payload）

**Project Type**: library + MCP tool server

**Performance Goals**: 提案扫描跟在 pulse 之后，不额外打 IMAP

**Constraints**: 无 SMTP；无写邮箱；模型置信度不能单独授权；通道失败不得当确认

**Scale/Scope**: 读工具 `twinbox_action_proposals` + 本地审 `twinbox_action_review`

## Constitution Check

- **I**: 本增量无邮箱副作用；提案/审计/本地 review 是 local-only。✅
- **II**: 卡片 payload 用引用 + 有界摘要，无全文。✅
- **IV**: 新工具 additive；九工具保留。✅
- **ADR-002 / ADR-003**: 策略未命中不执行；通道委托宿主 webhook。✅

## Project Structure

```text
twinbox_core/actions.py
tests/test_actions.py
runtime/audit/actions.jsonl   # state root, not tracked
```

## Phase 1: Design

提案字段：`proposal_id`、`idempotency_key`、`policy_id`/`policy_version`、`action_type`、`target_scope`、`thread_key`、`evidence_refs`、`draft_payload`、`draft_payload_hash`、`confirmation`、`card_payload`、`status`（`draft` / `awaiting_confirmation` / `needs_human` / `confirmed` / `rejected` / `expired`）。

`twinbox_action_review` 只改本地状态。确认卡片不在 Twinbox 内投递。策略外扫描结果必须是空列表，不得「建议用户手动转发」冒充策略命中。

## Phase 2: HITL confirmation token (implemented locally)

- `scan_proposals()` 以 canonical、bounded `draft_payload` 计算 SHA-256，并把原 token 仅放进 card；持久 proposal/audit 只保存 token hash。
- 有唯一 policy target 时依次审计 `draft_created → confirmation_issued`，状态为 `awaiting_confirmation`；目标歧义保持 `needs_human`，不发 token。
- `twinbox_action_review(confirm)` 必须带 token；缺失、无效、重放、过期、payload hash 不匹配均返回结构化错误且不确认。payload 变化会先审计旧 token 过期，再原地重发新的 draft/token。
- `card_payload.interaction` 明确 `must_stop_agent_turn` 与禁止同回合确认；根 `SKILL.md` 把它设为 Agent 级指令。MCP 不承担身份验证，宿主必须只在后续人类消息中转交 token。
- `confirmed` 仅记录本地审计与 `execution.status=blocked_read_only`；不实现 `executing`、SMTP、IMAP 写入或 webhook 投递。
- `tests/test_actions.py` 覆盖 TTL、token hash、缺 token、重放、payload 变化、篡改、CLI 参数转发及无执行状态；`tests/mcp-smoke.mjs` 固化 MCP 参数 schema。
