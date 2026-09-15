---
description: "Task list for policy-governed workflow automation (dry-run)"
---

# Tasks: Policy-Governed Workflow Automation (dry-run)

**Input**: `/specs/006-policy-governed-workflow-automation/`

**Prerequisites**: ADR-002, ADR-003, `003` action_policy 声明

## Phase 1: Setup

- [x] T001 在样例 pack 中声明一条 action_policy（允许的 action_type / target_scope / 需确认）

## Phase 2: User Story 1 - 策略内提案 (P1) 本增量替代「自动执行」

- [x] T002 [US1] `twinbox_core/actions.py`：扫描 pack 策略 + 事件/投影，生成提案；策略外 0 提案
- [x] T003 [US1] 写 `runtime/audit/actions.jsonl`（尝试即写，含 policy 版本与幂等键）
- [x] T004 [US1] 相同幂等键重放不新增第二条 proposed 成功记录
- [x] T005 [P] [US1] `tests/test_actions.py`：命中策略有提案；未命中空列表；重放幂等

## Phase 3: User Story 3 - 目标歧义停机 (P1)

- [x] T006 [US3] 目标无法唯一解析 → 提案 status=`needs_human`，不填可执行 target
- [x] T007 [US3] 模型提议范围外目标 → 拒绝并审计

## Phase 4: User Story 2 - 确认卡片 payload (P2)

- [x] T008 [US2] 输出宿主 webhook 形状的 `card_payload`（引用 + 有界摘要）；不接飞书 SDK
- [x] T009 [US2] 通道超时/失败不得把提案标为 confirmed（本地 review 才改状态）
- [x] T010 [P] [US2] CLI/MCP：`twinbox_action_proposals`（读）+ `twinbox_action_review`（本地状态）

## Phase 5: Polish

- [x] T011 FR-007：默认路径仍只读；无 SMTP 调用点
- [x] T012 `tests/mcp-smoke.mjs` 更新工具列表（若注册新工具）

## Dependencies

- T002 依赖 `003` pack/rules 与 `005` 投影（可先用夹具事件）
- T008 不投递通道
- 真实 SMTP / 写邮箱不在本任务列表


## Phase 6: Draft / HITL confirmation token (Planned — enterprise Phase 4)

- [ ] T013 Reuse `runtime/actions/proposals.json`; add draft payload + confirmation token fields
- [ ] T014 Token TTL (~5m), single-use; payload hash mismatch → expire
- [ ] T015 Agent turn MUST stop after issuing token (no same-turn self-confirm)
- [ ] T016 State machine transitions + audit events
- [ ] T017 Tests: replay / expire / tamper cannot enter executing; still no SMTP
