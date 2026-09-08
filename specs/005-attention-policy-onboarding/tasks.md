---
description: "Task list for attention policy and onboarding"
---

# Tasks: Attention Policy and Onboarding

**Input**: `/specs/005-attention-policy-onboarding/`

**Prerequisites**: `003` pack loader；`002` pending/urgent 信号

## Phase 1: Setup

- [x] T001 定义 ≤5 问问卷 schema 与到 pack 字段的映射（`twinbox_core/onboard.py`）

## Phase 2: User Story 1 - 问卷写包 (P1)

- [x] T002 [US1] CLI `onboard`（及可选 MCP `twinbox_onboard`）：写入 `~/.twinbox/packs/user.yaml`，校验走 `pack.py`
- [x] T003 [US1] 跳过通告类 → 默认 reference 规则写入包
- [x] T004 [P] [US1] `tests/test_onboard.py`：≤5 问产出合法 pack；再 sync 可读该包

## Phase 3: User Story 2 - 三投影 (P1)

- [x] T005 [US2] `twinbox_core/project.py`：产出 `action_required` / `watch` / `reference`；urgency / actionability / interest / sensitivity 分轴
- [x] T006 [US2] 注入 `latest_mail` / `todo` JSON（additive）；每项 `why` + 投影桶
- [x] T007 [P] [US2] `tests/test_project.py`：当天审批 → action_required；重要不立刻行动 → watch；制度邮件 → reference；紧急无需回复不进 pending reply

## Phase 4: User Story 3 - 与 002 共存 (P2)

- [x] T008 [US3] 无 pack 时安全默认偏 reference；规则与 LLM 冲突时硬约束优先并写 diagnostics
- [x] T009 文档：本目录任务不复制 MIME 解码

## Phase 5: Polish

- [x] T010 MCP 既有工具名不变；`tests/mcp-smoke.mjs`

## Dependencies

- T002 依赖 `003` T003 pack 校验
- T005 依赖 `002` recipient_role / pending 与 `003` rules
