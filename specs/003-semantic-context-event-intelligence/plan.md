# Implementation Plan: Semantic Context and Event Intelligence

**Branch**: `master` (spec dir `003-semantic-context-event-intelligence`) | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-semantic-context-event-intelligence/spec.md`

## Summary

声明式 Semantic Pack（routing-rules 超集）驱动事件理解与候选选择。入库时对每封新邮件做自托管 embedding（ADR-003），分析用结构信号 + `attention_hints` 相似度选 30–40 线程。硬条件可 `skip_llm`；语义条件三段余弦。分析 prompt 采用有界字符预算，保留 opaque 证据引用并优先最新正文，避免数百封邮件直接耗尽上下文。材料导入为可选 extras。关键词不进核心。

## Technical Context

**Language/Version**: Python 3.11+；Node.js 18+（MCP 薄封装）

**Primary Dependencies**: stdlib；现有 `llm.py`（urllib，直连自托管 vLLM）；embedding HTTP 客户端同风格。`openpyxl` / `python-docx` 为 optional extras，核心无它们须能跑。

**Storage**: 包文件在 `config/packs/`（追踪样例）与 `~/.twinbox/packs/`（用户包）；向量 sidecar `runtime/context/embeddings/`（state root，不进仓）。

**Testing**: pytest + 构造邮件 + mock HTTP embedding/LLM；禁止真实 IMAP。

**Target Platform**: macOS / Linux 本机 MCP；部署主机热更验证。

**Project Type**: library + MCP tool server

**Performance Goals**: ~5k 封纯 Python 余弦可接受；embedding 失败不得阻塞 fetch；单次分析 prompt 默认不超过 1,000,000 字符，预算诊断不落正文。

**Constraints**: 仅自托管 embedding/LLM；禁止公有云；禁止 numpy/torch/sentence-transformers/LangChain；平台 ingest 不带向量与正文。

**Scale/Scope**: 单邮箱；一期 JSON sidecar；>2 万封换 zvec（不在本增量实现）。

## Constitution Check

- **I**: 只读；材料导入只写本地 pack 片段。✅
- **II**: 向量留在 state root；平台向输出无全文。✅
- **III**: 实体/规则只在 pack。✅
- **IV**: 既有 9 工具名不变；语义搜索走 `thread_inspect` 既有 `query` 或 additive 字段；材料导入可为新 CLI/工具。✅
- **V**: 端点 URL 与密钥只在 `~/.twinbox/`。✅
- **ADR-001 / ADR-003**: pack 禁可执行代码；检索主干自托管。✅

## Project Structure

```text
twinbox_core/
├── pack.py            # 加载 / 校验 / 指纹
├── embeddings.py      # HTTP 客户端 + sidecar + 余弦
├── select.py          # 候选选择
├── rules.py           # 硬条件 skip_llm + 语义三段
└── material_import.py # 可选 extras 导入器
config/packs/minimal.yaml
config/packs/sample-enterprise.yaml
tests/test_pack.py
tests/test_embeddings.py
tests/test_rules.py
tests/test_select.py
```

## Phase 0: Research

Pack schema = archive `routing_rules.py` 超集：`entities` / `relations` / `classification` / `attention_hints` / `routing_conditions` / `action_policy`。语义条件带 `utterances` 与 `threshold_high` / `threshold_low`。

硬条件（发件人、文件夹、`recipient_role`、header 正则）可 `skip_llm: true`。语义中间带才问 LLM。

材料导入：xlsx/docx → pack 片段（关注名单、实体别名）；缺 optional 包时 CLI 返回 structured error。

## Phase 1: Design

`analyze.py` 改为消费 `select.choose_candidates()` 结果，不再盲切 `envelopes[:100]`。`search_threads` 增加语义路径（同一 sidecar）。Rerank 未配 `rerank.api_url` 时 identity（默认不接）。

`analyze.py` 在组装候选线程后先写入 metadata 与 opaque `evidence_id`，再按“最新正文优先、历史正文稳定排序”的顺序填充预算。默认字符上限为 1,000,000，可由 `TWINBOX_ANALYSIS_PROMPT_MAX_CHARS` 调整但始终钳制在 512–4,000,000；`runtime/validation/phase-4/analysis-prompt-diagnostics.json` 仅保存字符数、估算 token 数、纳入/省略数量与线程统计。

校验拒绝：`script` / `python` / `exec` / `!include` 可执行键、内嵌代码块。
