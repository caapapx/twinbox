# Tasks: Everything Mail Adapter

**Input**: Design documents from `/specs/001-everything-mail-adapter/`

**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 历史固定六轴路径的处置与证据夹具边界；动态语义已收敛到 `013` Semantic Pack。

- [x] T001 [superseded by 013] 不在 `config/extract-profiles.yaml` 新建固定六轴。动态、不透明的轴和值由 `013` 的版本化 `config/packs/*.yaml` Semantic Pack 声明；平台消费者不得获得六键枚举。
- [x] T002 [P] 已在 `tests/fixtures/adapter_events/v1.json` 准备周报/风险/计划变更的**合成、仅信封字段**样例，并由 `tests/test_adapter_event_fixtures.py` 验证动态 Semantic Pack 分类与无正文事件输出（2026-09-20）；不是人工金标、召回/ROI 语料，T025 继续等待受权 owner 的独立质量集。

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 多账号模型与凭据 vault 是所有用户故事的前置

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 扩展 `twinbox_core/config.py`：账号列表模型（account_id、type=personal/shared、连接参数、vault 引用），向后兼容单账号配置
- [x] T003b 持久默认箱：`set_default_account` / `accounts set-default`；`list` 带 `is_default`；删当前默认回落到剩余账号；查询省略 `account_id` 走 `default_account_id`
- [x] T004 实现 `twinbox_core/vault.py`：Fernet 对称加密的本地 vault（`~/.twinbox/vault.enc`），主密钥经系统 keyring 或 `~/.twinbox/.vault_key`（0600）
- [x] T005 [P] 新增 `tests/test_vault.py`：加解密往返、存储文件无明文口令、存在性布尔查询
- [x] T006 扩展 `twinbox_core/pulse.py`：按账号循环同步，同步记录携带 account_id

**Checkpoint**: 多账号配置 + 加密 vault 就绪，用户故事可并行开始

---

## Phase 3: User Story 1 - 公共邮箱只读接入 (Priority: P1) 🎯 MVP

**Goal**: 公共邮箱以只读 IMAP 接入，进入现有线程分析与队列视图

**Independent Test**: 登记公共邮箱 → `python3 -m twinbox_core.cli sync --json` → 队列出现该账号线程且服务器侧无写操作

### Implementation for User Story 1

- [x] T007 [US1] 参数化 `twinbox_core/imap_fetch.py` 支持按 account_id 拉取，确认全程只读（无 STORE/DELETE/COPY 类命令）
- [x] T008 [US1] 扩展 `twinbox_core/cli.py`：`accounts add/list/remove` 子命令（凭据写入 vault，输出仅含 `password_set` 布尔值）
- [x] T009 [US1] 扩展 `mcp-server.mjs`：注册 `twinbox_accounts` 工具，复用既有 spawn CLI 与 ok/data/error/recovery_tool 封装
- [x] T010 [US1] 只读回归验证：对测试公共邮箱跑完整同步，断言 IMAP 会话日志无任何写命令

**Checkpoint**: User Story 1 独立可用（MVP）

---

## Phase 4: User Story 2 - Everything ingest 输出 (Priority: P2)

**Goal**: 输出「引用 + 六轴 attributes」的 ingest envelope，平台只收引用不收全文

**Independent Test**: 对已知邮件调用 ingest 工具，断言 envelope 含六轴、无 body 字段、游标可重放

### Implementation for User Story 2

- [x] T011 [US2] 新增 `twinbox_core/adapter.py`：ingest envelope 组装（reference + attributes + cursor），摘要 ≤280 字截断
- [x] T012 [superseded by 013] 不在 `twinbox_core/llm.py` 固化六轴 schema。`013` 的 Pack→分类快照→opaque projection 是当前路径；任何 provider 保持 TwinBox 内部可选、默认关闭，不能成为 adapter 契约。
- [x] T013 [P] [US2] 新增 `tests/test_adapter.py`：schema 断言、无全文扫描断言（body/html/attachment 字段不存在）、cursor 重放幂等
- [x] T014 [US2] 扩展 `twinbox_core/cli.py`：`ingest` 子命令（since 游标、分页上限）
- [x] T015 [US2] 扩展 `mcp-server.mjs`：注册 `twinbox_ingest` 工具
- [x] T016 [US2] Pack语义轴驱动的出站降级：默认`reference_only`；仅Pack显式轴/值可选择允许、截断或省略摘录，未匹配值fail-safe且保留引用（2026-09-20本地合成契约验收）

**Checkpoint**: User Stories 1 和 2 均独立可用

---

## Phase 5: User Story 3 - 多用户集中管理与凭据加密 (Priority: P2)

**Goal**: 多账号集中管理闭环，凭据全链路无明文

**Independent Test**: 登记两个账号 → vault 文件无明文 → 状态工具只输出存在性布尔值 → 重启后仍可解密

### Implementation for User Story 3

- [x] T017 [US3] `twinbox_status` / `twinbox_setup` 输出审计：移除任何凭据回显，统一为 `password_set: bool`
- [x] T018 [US3] 日志与错误路径审计：异常信息不拼接凭据材料；`recovery_tool` 指引不含敏感值
- [x] T019 [US3] 账号隔离断言：ingest/queue 记录均可溯源 account_id，跨账号无串数据
- [x] T020 [US3] 明文扫描校验：对 `~/.twinbox/vault.enc` 与仓库追踪文件 grep 已知测试口令，命中数为 0

**Checkpoint**: User Stories 1、2、3 均独立可用

---

## Phase 6: User Story 4 - 事件抽取 (Priority: P3)

**Goal**: 从邮件流抽取 weekly_report / risk / plan_change 结构化事件，引用式输出并按稳定 ID 去重

**Independent Test**: 对 T002 夹具邮件运行事件抽取，断言事件类型正确、字段完整、无正文、重复抽取去重

### Implementation for User Story 4

- [x] T021 [superseded by 013] `twinbox_core/events.py` 已作为引用式 Pack 事件投影存在；不补固定三类事件或以 `llm.py` 为必经抽取通路。稳定身份、证据与可配置事件语义以 `013` 的 Pack/分类合同为准。
- [x] T022 [superseded by 013] 不在 `config/extract-profiles.yaml` 固定 weekly_report/risk/plan_change。事件类型和字段由 `config/packs/*.yaml` 声明；三个类型只可作为 Pack fixture，不得成为核心枚举。
- [x] T023 [superseded by 013] 当前 `events` CLI/read path 与 ingest 的引用式事件链接已存在；不重建旧型端到端抽取链路。真实 Pack/source grant 与现场回放仍归 `013/T021` 的独立 gate。
- [x] T024 [US4] 扩展 `mcp-server.mjs`：注册 `twinbox_events` 工具
- [ ] T025 [US4] 以受权 owner 的独立、冻结 development/holdout 人工金标验证 holdout 主事件召回率 ≥ 80%；`tests/evaluations/adapter_event_recall.py` 与 `tests/test_adapter_event_recall.py` 已提供离线、无网络的受控 harness（仅伪名信封字段、source grant / owner approval / frozen split、无输入字段回显）。合成 T002 fixture 只能做回归，不能关闭本任务；有语义规则时 hard-rule 模式明确阻断全分类质量结论，必须以获批的离线预测集复跑。未达标才在 `013` Pack 规则上迭代，不能恢复 T022 固定事件枚举。

**Checkpoint**: 全部用户故事独立可用

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 跨故事收尾

- [x] T026 [P] 扩展 `tests/mcp-smoke.mjs`：新增三个工具的端到端冒烟
- [x] T027 [P] 更新 `CLAUDE.md` 关键路径表（新增 adapter/events/vault 模块与新工具）
- [x] T028 全文外泄端到端校验：对平台可见的全部工具响应做自动化全文扫描（2026-09-20：`tests/mcp-output-safety.mjs` 通过真实MCP stdio边界枚举并调用全部17个已注册工具；注入正文形字段、异常文本与非结构化输出均不回显，显式 `platform_output_redacted` / fail-closed；仅为本地合成CLI回归，不替代真实邮箱/现场验收）
- [x] T029 既有 9 个 `twinbox_*` 工具回归：签名与 envelope 形状不变

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-6)**: All depend on Foundational phase completion
  - US1 (P1) 先行交付 MVP；US2 与 US3 可并行（不同模块：adapter/llm vs vault 审计/状态输出）
  - US4 (P3) 依赖 US2 的 envelope 结构稳定（事件 ID 链接进 envelope）
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: 仅依赖 Foundational；无故事间依赖
- **User Story 2 (P2)**: 依赖 Foundational + T001 轴配置；与 US3 无耦合
- **User Story 3 (P2)**: 依赖 Foundational 的 vault；与 US2 可并行
- **User Story 4 (P3)**: 依赖 US2 envelope 结构稳定后接入 `events` 字段

### Parallel Opportunities

- T001 / T002 并行
- T005 与 T003/T004 并行（测试先行）
- US2（T011–T016）与 US3（T017–T020）可并行推进
- T026 / T027 并行

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: 公共邮箱只读接入独立验证
5. 可先作为部门内部工具交付试用

### Incremental Delivery

1. Setup + Foundational → 多账号与 vault 就绪
2. +US1 → 公共邮箱接入（MVP）
3. +US2 → 平台可消费 ingest envelope（adapter 核心价值）
4. +US3 → 企业级凭据安全闭环
5. +US4 → 事件驱动的周报/风险/计划变更数据层


## Legacy-path disposition (2026-09-20)

`[superseded by 013]` is a terminal planning disposition, **not** a claim that the literal legacy task was implemented or that its original acceptance test passed. It prevents a second, fixed six-axis / fixed-event / mandatory-LLM pipeline from being built beside the current Semantic Pack contract. The only 001 quality claim that remains open is evidence-backed recall under T002/T025; it cannot be closed by synthetic fixtures, a provider mock, or a green local unit suite.

## Remaining beyond confirmed Phase 1 gate (2026-09-15)

Confirmed enterprise slice = Phase 0 contracts + Phase 1 read plane + min observability.
Open 001 evidence work is intentionally limited to T002/T025: synthetic fixture coverage may support local regression, but the ≥80% event-recall claim requires approved private owner gold and a held-out evaluation. T001/T012/T021–T023 are superseded by the `013` Pack contract rather than implemented under the obsolete fixed-axis path. T016 is locally closed by the 2026-09-20 Pack-axis evidence-contract regression, and T028 by the MCP-boundary regression; neither proves a live mailbox or provider path.
