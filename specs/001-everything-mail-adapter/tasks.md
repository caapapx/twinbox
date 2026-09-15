# Tasks: Everything Mail Adapter

**Input**: Design documents from `/specs/001-everything-mail-adapter/`

**Prerequisites**: plan.md (required), spec.md (required for user stories)

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 归类轴配置与测试夹具先行

- [ ] T001 在 `config/extract-profiles.yaml` 中定义六轴归类结构（person / thing / intent / urgency / sensitivity / thread）与初始取值规则
- [ ] T002 [P] 在 `tests/` 下准备测试夹具：含周报/风险/计划变更语义的样例邮件（`tests/fixtures/`）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 多账号模型与凭据 vault 是所有用户故事的前置

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 扩展 `twinbox_core/config.py`：账号列表模型（account_id、type=personal/shared、连接参数、vault 引用），向后兼容单账号配置
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
- [ ] T012 [US2] 在 `twinbox_core/llm.py` 增加 envelope 归类输出 schema（六轴，opaque string），接入 T001 的轴配置
- [x] T013 [P] [US2] 新增 `tests/test_adapter.py`：schema 断言、无全文扫描断言（body/html/attachment 字段不存在）、cursor 重放幂等
- [x] T014 [US2] 扩展 `twinbox_core/cli.py`：`ingest` 子命令（since 游标、分页上限）
- [x] T015 [US2] 扩展 `mcp-server.mjs`：注册 `twinbox_ingest` 工具
- [ ] T016 [US2] 敏感轴降级：sensitivity 命中高敏时摘要进一步截断或省略，引用保留

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

- [ ] T021 [US4] 新增 `twinbox_core/events.py`：事件 schema（稳定 ID = hash(account_id, message_id, event_type, 键字段)）与 LLM 抽取通路（复用 `extract.py` 模式）
- [ ] T022 [US4] 在 `config/extract-profiles.yaml` 增加三类事件的判定规则与抽取字段定义
- [ ] T023 [US4] 扩展 `twinbox_core/cli.py`：`events` 子命令；事件 ID 链接进 ingest envelope 的 `events` 字段
- [x] T024 [US4] 扩展 `mcp-server.mjs`：注册 `twinbox_events` 工具
- [ ] T025 [US4] 用 T002 夹具验证召回率 ≥ 80%（人工标注对照），未达标则调整 T022 规则迭代

**Checkpoint**: 全部用户故事独立可用

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 跨故事收尾

- [x] T026 [P] 扩展 `tests/mcp-smoke.mjs`：新增三个工具的端到端冒烟
- [x] T027 [P] 更新 `CLAUDE.md` 关键路径表（新增 adapter/events/vault 模块与新工具）
- [ ] T028 全文外泄端到端校验：对平台可见的全部工具响应做自动化全文扫描
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


## Remaining beyond confirmed Phase 1 gate (2026-09-15)

Confirmed enterprise slice = Phase 0 contracts + Phase 1 read plane + min observability.
Still open for fuller 001 US2/US4: T001–T002 axes/fixtures, T012 LLM schema, T016 sensitivity truncate,
T021–T023/T025 richer event extraction & recall, T028 full-body scan across all tool responses.
