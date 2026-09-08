# Implementation Plan: Analysis Correctness

**Branch**: `master` (spec dir `002-analysis-correctness`) | **Date**: 2026-09-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-analysis-correctness/spec.md`

## Summary

在现有 `twinbox_core` 抓取 → 单次 LLM 分析 → pulse 投影链路上：解码 MIME 为 UTF-8 纯文本；同一 FETCH 带上 To/Cc/List-Id 并计算 `recipient_role`；两阶段采样（候选 45 / 正文 24）；按线程最新邮件判定 pending；同一套 `normalize_thread_key` join 标签。MCP 对过期 pulse 自动同步。extract / inspect / status 暴露可读正文。`tests/eval_replay.py` 记录回放基线。工具名与既有 JSON 字段保持兼容。关键词打分不进核心（属 `003` pack `attention_hints`）。

## Technical Context

**Language/Version**: Python 3.11+（`twinbox_core/`），Node.js 18+（`mcp-server.mjs`）

**Primary Dependencies**: stdlib `email` / `imaplib`；现有 `llm.py`、PyYAML；无新第三方包

**Storage**: `~/.twinbox/runtime/` 既有 JSON/YAML artifacts；新增字段一律 additive

**Testing**: pytest（构造 MIME 夹具 + mock LLM）+ `tests/mcp-smoke.mjs`

**Target Platform**: macOS / Linux 本机 MCP stdio

**Project Type**: library + MCP tool server

**Performance Goals**: 解码在现有 body 采样上限内完成；不增加真实 IMAP 往返次数

**Constraints**: 真实邮箱只读；MCP 工具名与既有字段不删不改类型；凭据不外泄；平台 ingest（001）仍禁全文

**Scale/Scope**: 单邮箱、现有 9 工具；不实现 001 多账号/ingest

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Mailbox Mutation Boundary**: 只改本地解析、分析与 MCP 读路径；不新增 send/move/delete/archive/flag。✅
- **II. Full Text Never Leaves twinbox (to platforms)**: 本地 MCP 返回解码纯文本符合 constitution 1.2.0；不把全文写入 Agent OS。✅
- **III. Classification Axes Stay in twinbox**: 动作词表放 `config/action-verbs.yaml`；不锁进平台。✅
- **IV. Stable Tool Contract Surface**: 九工具名不变；staleness / attachments / diagnostics / pipeline 均为新字段。✅
- **V. Credentials Never Leak**: 测试夹具不含真实口令；status 继续脱敏。✅
- **Trunk**: 实现落在 `master`，不为本 feature 建长期 `feat/*` 分支。✅

## Project Structure

### Documentation (this feature)

```text
specs/002-analysis-correctness/
├── spec.md
├── plan.md
├── research.md
└── tasks.md
```

### Source Code (repository root)

```text
twinbox_core/
├── imap_fetch.py      # MIME 解码、HEADER TO/CC/LIST-ID、recipient_role、两阶段采样
├── analyze.py         # 线程分组 prompt、SYSTEM_PROMPT、resolved_by_reply
├── pulse.py           # normalize_thread_key join、score aging
├── extract.py         # body_text / attachments / hour filter
├── cli.py             # sync degraded、status pipeline、inspect
└── config.py          # 可选 staleness 阈值
mcp-server.mjs         # stale auto-sync
config/action-verbs.yaml
tests/
├── test_mime_decode.py
├── test_thread_key_join.py
├── test_recipient_role.py
├── test_extract.py
├── eval_replay.py
└── mcp-smoke.mjs
```

## Phase 0: Research

见 [research.md](./research.md)。无未决 NEEDS CLARIFICATION。

## Phase 1: Design

不新增独立服务。解码函数从 `imap_fetch` 抽出可单测的纯函数，供 fetch / extract / inspect 共用。thread_key 归一化从 `pulse._normalize_thread` 提升为共享函数，analyze 写出前先 normalize。

IMAP `BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE MESSAGE-ID TO CC LIST-ID IN-REPLY-TO REFERENCES)]` 与现有 FETCH 合并，不多一次往返。`recipient_role` 语义迁自 archive `context_builder.py`（`_parse_mime_recipient_role` + `_aggregate_thread_recipient_role`），不迁 `envelope_recipient_probe.py`。

两阶段采样数值（plan 常量，非 constitution）：`max_thread_candidates=45`，`max_body_fetch=24`。粗排用结构信号（new/unread/`recipient_role`/recency），**禁止**把「周报/台账/部署」硬编码进核心。

`tests/eval_replay.py` 迁自 archive `evaluation.py` 的对照思路：读回放目录，输出 JSON 指标（waiting_on_me 误报、join miss、attention 计数），不连真实 IMAP。

## Constitution Check (post-design)

同上，无违规。实现阶段禁止把 raw MIME 写进平台契约或追踪凭据。
