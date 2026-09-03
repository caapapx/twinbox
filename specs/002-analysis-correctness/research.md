# Research: Analysis Correctness

## 决策

| 议题 | 决定 | 理由 |
|------|------|------|
| MIME 解析 | stdlib `email.message_from_bytes`，优先 text/plain | 零新依赖；与 constitution / ponytail 一致 |
| 正文给谁 | 本地 MCP 可返回解码正文；Agent OS ingest 仍禁全文 | constitution 1.1.0 |
| thread_key | 单一 `normalize_thread_key()`，分析写出前与 pulse join 时都用 | 消灭大小写/Re: 丢标签 |
| stale 阈值 | 默认 4h，可配置 | 工作时段可接受；避免每次 latest_mail 都打 IMAP |
| 采样 key | `folder#uid` | 避免 INBOX/Sent UID 碰撞 |
| 采样顺序 | date 倒序取最新 N | 大批量时最新邮件才有正文 |
| 实现分支 | 在 `main` 上改，不为 002 建 `feat/*` | 主干治理 |

## 事故证据（2026-09-03）

- `analyze.py` `body_preview[:300]` + 原始 MIME → LLM 看不见「请登记处理」/「同意」
- `pulse._queue_membership` 精确匹配未归一化 key → pending 5 丢 4
- `mcp-server.mjs` `needsSync` 只认 pulse 缺失
- `cli.cmd_sync` 忽略 `run_analysis` 失败仍 `ok: True`

## 不做

- 不实现 001 ingest / 多账号 vault
- 不重写 git 历史
- 单元测试不连真实 IMAP/LLM
