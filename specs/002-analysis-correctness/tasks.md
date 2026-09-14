---
description: "Task list for analysis correctness"
---

# Tasks: Analysis Correctness

**Input**: Design documents from `/specs/002-analysis-correctness/`

**Prerequisites**: plan.md (required), spec.md (required), research.md

**Tests**: P0/P1 必须带 pytest 夹具；禁止依赖真实 IMAP/LLM。

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup

**Purpose**: 回放目录与共享测试夹具

- [x] T001 复制 `~/.twinbox`（或 `TWINBOX_STATE_ROOT`）到一次性回放目录，只读真实状态；记录辽宁白名单 / 验收登记 / pending 丢标签的复现结果到后续 `EVOLUTION.md` 草稿
- [x] T002 [P] 在 `tests/fixtures/` 加入 GB2312 + quoted-printable + base64 附件的 multipart 样例 `.eml`

---

## Phase 2: Foundational (Blocking)

**Purpose**: 解码与 thread_key 是所有故事的前置

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 在 `twinbox_core/imap_fetch.py` 抽出 `decode_message_bytes()`：multipart、CTE、charset、附件元数据、截断作用在纯文本上
- [x] T004 在 `twinbox_core/pulse.py` 抽出并导出 `normalize_thread_key()`，供 analyze 写出与 pulse join 共用
- [x] T005 [P] 新增 `tests/test_mime_decode.py`：夹具可读中文、无 MIME 残留、附件只有元数据
- [x] T006 [P] 新增 `tests/test_thread_key_join.py`：Re:/回复/大小写/尾部日期归一化一致

**Checkpoint**: 解码与 key 归一化可单测通过

---

## Phase 3: User Story 1 - 读到的正文是人话 (Priority: P1) 🎯 MVP

**Goal**: fetch / sample / extract / analyze 预览都走解码纯文本

- [x] T007 [US1] `fetch_bodies_imap` / `sample_bodies_imap` 调用 `decode_message_bytes`；采样 key 用 `folder#uid`；两阶段采样：候选线程 45、正文补拉 24（`twinbox_core/imap_fetch.py`）
- [x] T007b [US1] envelope FETCH 增加 `TO CC LIST-ID IN-REPLY-TO REFERENCES`；写入信封 `to`/`cc`/`list_id`/`in_reply_to`/`references`（`twinbox_core/imap_fetch.py`）
- [x] T007c [US1] 实现 `recipient_role` 信封判定与线程聚合（direct/cc_only/group_only/indirect/unknown）；逻辑迁自 archive `context_builder.py`，不迁探针文件（`twinbox_core/imap_fetch.py` 或新 `twinbox_core/recipient.py`）
- [x] T007d [P] [US1] 新增 `tests/test_recipient_role.py`：To 命中=direct；仅 Cc=cc_only；List-Id 且不在 To/Cc=group_only
- [x] T008 [US1] `analyze._build_prompt` 用解码 body，预览 ≥800 字，最新一封可到 2000（`twinbox_core/analyze.py`）
- [x] T009 [US1] `extract.envelope_to_report` 输出解码 `body_text`、`body_truncated`、`attachments`（`twinbox_core/extract.py`）

**Checkpoint**: US1 夹具测试通过

---

## Phase 4: User Story 2 - 待办跟最新一封走 (Priority: P1)

**Goal**: prompt 按线程分组；最新邮件决定 pending

- [x] T010 [US2] `_build_prompt` 按 thread_key 分组、时间倒序、标记 `is_latest`（`twinbox_core/analyze.py`）
- [x] T011 [US2] 更新 `SYSTEM_PROMPT`：waiting_on_me 以最新邮件为准；审批回复不得再 pending；禁止推测性 why；支持 `resolved_by_reply`
- [x] T012 [US2] mock LLM 或规则夹具：同意回复清 pending；「请登记处理」进入 pending/urgent（`tests/`）

**Checkpoint**: US2 验收场景可测

---

## Phase 5: User Story 3 - 分析标签全部看得到 (Priority: P1)

**Goal**: 标签 join 不再静默丢失

- [x] T013 [US3] `_queue_membership` 与 `build_activity_pulse` 两侧都 `normalize_thread_key()`（`twinbox_core/pulse.py`）
- [x] T014 [US3] 未命中写入 `diagnostics.queue_join_misses`；`cmd_status` 暴露该字段（`twinbox_core/pulse.py`、`twinbox_core/cli.py`）
- [x] T015 [US3] 回归：构造 5 条大小写不一致的 pending，join 后 0 miss（`tests/test_thread_key_join.py`）

**Checkpoint**: US3 完成；P1 正确性闭环

---

## Phase 6: User Story 4 - 过期快照会刷新或失败 (Priority: P2)

**Goal**: stale ≠ missing；失败不装成功

- [x] T016 [US4] CLI `latest-mail` / `todo` / `weekly` 输出 `staleness`（`twinbox_core/cli.py`）
- [x] T017 [US4] `mcp-server.mjs`：`latest_mail` / `todo` / `weekly` 在 pulse 缺失时自动 `sync --json`；仅 stale 时直接返回快照与 `staleness`，不阻塞 IMAP。
- [x] T017a [US4] 2026-09-11：加入显式 `sync --job quick-refresh`（跳过 `run_analysis`，pulse 加 `analysis_generated_at` / `analysis_skipped`）；后续为消除 86s 读路径阻塞，stale 不再自动调用它，缺失仍完整同步。
- [x] T018 [US4] 测试或脚本：generated_at 回拨后必须走同步路径

**Checkpoint**: US4 完成

---

## Phase 7: User Story 5 - 同步报告诚实、抽取可读 (Priority: P2)

**Goal**: sync degraded + extract 小时过滤

- [x] T019 [US5] `cmd_sync` 在 `run_analysis` 失败时 `degraded:["analysis"]` + pulse `stale_analysis`；增加 `consistency` 与 `watermark_range`（`twinbox_core/cli.py`、`imap_fetch.py`）
- [x] T020 [US5] extract 增加 `from_hour` / `to_hour`（`twinbox_core/extract.py`、`cli.py`、`mcp-server.mjs` 入参 additive）
- [x] T021 [US5] 扩展 `tests/test_extract.py`：无 MIME 残留、小时过滤

**Checkpoint**: US5 完成

---

## Phase 8: User Story 6 - 注意力列表与体检可用 (Priority: P3)

**Goal**: 排序校准、inspect 正文、pipeline 健康

- [x] T022 [US6] sla_risk 老化与 `config/action-verbs.yaml` action_hint 加权；pulse 顶层 `score_legend`（`twinbox_core/pulse.py`）
- [x] T023 [US6] `search_threads` / thread-inspect 附加 `latest_message` 或 `body_unavailable`（`twinbox_core/pulse.py`、`cli.py`）
- [x] T024 [US6] `cmd_status` 增加 `pipeline` 与 missed_runs（对照 `config/schedules.yaml`）

**Checkpoint**: US6 完成

---

## Phase 9: Polish

- [x] T025 跑 `tests/mcp-smoke.mjs` 全绿
- [x] T026 写 `EVOLUTION.md`（SYSTEM_PROMPT diff、回放前后对比）；`twinbox-evolution-prompt.md` 顶部指向本 spec
- [x] T027 确认未改真实邮箱、未提交凭据
- [x] T028 [P] 审计 `mcp-server.mjs` 与 CLI JSON：既有字段不删不改类型；仅 additive（FR-013）
- [x] T029 在回放副本上重跑分析：验证 SC-002（辽宁不在 pending；验收登记进入 pending 或 daily_urgent）
- [x] T030 新增 `tests/eval_replay.py`：读取回放目录，输出 waiting_on_me 误报、join miss、attention 计数 JSON（不连真实 IMAP；源自 archive `evaluation.py`）

## Dependencies

- T003–T006 阻塞所有故事
- T007b → T007c（recipient_role 依赖 header 字段）
- T007d 可与 T008 并行
- US1 → US2（prompt 依赖解码正文）
- US3 可与 US2 并行，但依赖 T004
- US4–US6 依赖 US1 解码，不依赖彼此
- T024 的 missed_runs 执行器由 `007` 提供；本任务先暴露字段
- T030 不连真实 IMAP

## Implementation Strategy

1. 先 T001 复现，再 T003–T006
2. MVP = US1 + US2 + US3
3. 再 US4 / US5 / US6
4. 实现落在 `master`，不要建 `feat/002-*`
