# ADR-003: Retrieval Spine and External Services

- **Status**: Accepted
- **Date**: 2026-09-08
- **Deciders**: engineering (legacy capability migration review)
- **Related**: ADR-001 (semantic packs); ADR-002 (policy-governed writes); constitution I–II; `specs/002`–`007`

## Context

单次 LLM 分析受上下文预算约束。as-built 路径把信封截成 `envelopes[:100]` × 300 字，既截断又盲猜。`002` 加长预览后必须解决「选哪些线程给 LLM」。archive 用硬编码关键词粗排，违反 ADR-001。

外部服务边界此前未写死：LLM、embedding、向量库、rerank、确认通道、调度器各自可能被换成公有云或重型框架。

## Decision

### 1. 检索主干

fetch 后对每封**新**邮件（主题 + 解码正文前 N 字）做一次 embedding，增量持久到 `runtime/context/embeddings/`。分析时用「结构信号 + 与 pack `attention_hints` 的相似度」选 30–40 个候选线程给足正文。

同一索引服务：pack 语义规则预判、`thread_inspect` 语义搜索、`003` 事件归类、`004` 名单归属。

### 2. 端点边界

embedding / LLM **只允许自托管端点**：

- LLM：直连 vLLM OpenAI-compatible `:8000/v1`（部署在 251）。不引入网关、不自写 fallback 链。
- Embedding：239 Ollama `:11434` 或 vLLM 上的 `bge-m3` / `Qwen3-Embedding`。

公有云 embedding 属 constitution II 边界，禁止。向量是派生数据，留在 state root；平台 ingest（`001`）不携带向量与正文。

### 3. 存储分级

一期：JSON/npy sidecar + 纯 Python 余弦（约 5k 封量级）。接口单文件封装（`twinbox_core/embeddings.py`）。

超过约 2 万封或需要 FTS+过滤时换 `zvec`（in-process）。不引入托管向量库，不引入 LangChain / LlamaIndex。`zvec-grep` 仅开发侧检索代码/文档，不进 Twinbox 运行时。

### 4. 语义规则三段判定

余弦 ≥ high 命中、≤ low 不中、中间带才调一次 LLM。阈值在 pack 声明。思路借 agent-os `semantic_router.py`，代码自写（约 80 行），不引入 numpy / torch / sentence-transformers。

### 5. Rerank 二期

一期看召回。`thread_inspect` top-30→top-5 与 `004` 名单归属若精度不足，接 239 `:6006` bge-reranker。接口预留，一期不接。

### 6. 通道委托

`006` 确认/通知走 agent-os 8090（iFlyChat webhook + 卡片回调）。Twinbox 只产 card payload，不接飞书 SDK。

### 7. 调度委托

本机不跑 in-process 定时器 / Unix-socket daemon。`007` 提供 `schedule run-due` + 文件锁；由 239 crontab 驱动。

## Consequences

- `003` 必须实现 embed-at-ingest、候选选择、三段语义规则。
- 关键词 / 组织语义只进 Semantic Pack，不进 `twinbox_core`。
- 凭据与端点 URL 只在 `~/.twinbox/`；追踪配置只有占位。
- 一期不把 embedding 失败当成分析硬失败：缺向量时回退结构信号采样（`002` 两阶段），并在 diagnostics 标明 `embeddings_degraded`。
