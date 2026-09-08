---
description: "Task list for semantic context and event intelligence"
---

# Tasks: Semantic Context and Event Intelligence

**Input**: Design documents from `/specs/003-semantic-context-event-intelligence/`

**Prerequisites**: plan.md, spec.md, [ADR-003](../../docs/decisions/ADR-003-retrieval-spine-and-external-services.md)

**Tests**: pytest + mock HTTP；禁止真实 IMAP / 公有云 embedding。

## Phase 1: Setup

- [x] T001 建立 `config/packs/minimal.yaml` 与 `config/packs/sample-enterprise.yaml`（声明式，无业务硬编码进核心）
- [x] T002 [P] 文档化 pack schema 字段：entities / relations / classification / attention_hints / routing_conditions / action_policy（`specs/003-semantic-context-event-intelligence/plan.md` 已含；样例 YAML 须可校验）

## Phase 2: Foundational

- [x] T003 实现 `twinbox_core/pack.py`：加载 YAML、版本、指纹、拒绝可执行内容
- [x] T004 [P] `tests/test_pack.py`：合法包加载；含 script/exec 的包拒绝
- [x] T005 实现 `twinbox_core/embeddings.py`：自托管 HTTP embed、sidecar 读写、纯 Python 余弦；失败返回空并标记 degraded
- [x] T006 [P] `tests/test_embeddings.py`：mock HTTP；余弦单调；无 numpy 导入

**Checkpoint**: pack + embedding 可单测

## Phase 3: User Story 1 - 事件与候选 (P1)

- [x] T007 [US1] [US4] `twinbox_core/select.py`：结构信号 + attention_hints 相似度选 30–40 线程；无向量时回退 `002` 两阶段
- [x] T008 [US1] `analyze.py` 消费 `choose_candidates()`，去掉盲切 `envelopes[:100]`
- [x] T009 [US1] 事件记录：稳定 ID、类型、引用、抽取字段；平台向输出无正文（`twinbox_core/events.py` 或 analyze 旁路）
- [x] T010 [P] [US1] [US4] `tests/test_select.py`：hints 命中线程进入候选；embedding 失败仍能选出最新结构候选

## Phase 4: User Story 2 - 声明式规则 (P1)

- [x] T011 [US2] `twinbox_core/rules.py`：硬条件（sender/folder/recipient_role/header）可 `skip_llm`；语义三段余弦
- [x] T012 [US2] 分析前置应用 skip_llm 规则；后置允许 pack 覆盖标签
- [x] T013 [P] [US2] `tests/test_rules.py`：hard skip 不调 LLM；high 命中；low 不中；中间带调一次 mock LLM

## Phase 5: User Story 3 - 语义搜索与材料 (P2)

- [x] T014 [US3] `search_threads` / `thread_inspect` 语义路径走同一 sidecar（`twinbox_core/pulse.py` 或 `select.py`）
- [x] T015 [US3] `twinbox_core/material_import.py` + CLI `material-import`：openpyxl/python-docx 可选；缺依赖 structured error
- [x] T016 [P] [US3] 样例企业包夹具：事件类型由包声明，核心无「项目经理」实体名分支

## Phase 6: Polish

- [x] T017 MCP：既有工具名不变；材料导入可 CLI-only 或新 additive 工具
- [x] T018 `tests/mcp-smoke.mjs` 仍过
- [x] T019 确认无公有云 embedding、无 torch/numpy、无全文进平台字段

## Dependencies

- T007–T010 覆盖 US1 与 US4（候选选择）
- T011 依赖 T003
- T014–T015 覆盖 US3 材料与语义搜索（US4 语义路径）
- T015 不阻塞 US1/US2
