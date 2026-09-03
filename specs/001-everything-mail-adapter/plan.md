# Implementation Plan: Everything Mail Adapter

**Branch**: `001-everything-mail-adapter` | **Date**: 2026-08-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-everything-mail-adapter/spec.md`

## Summary

把 twinbox 从「单用户邮件智能 Skill」升级为 Agent OS Everything 过程数据层的邮件 adapter：在现有 `twinbox_core`（imap_fetch / analyze / extract / pulse / llm / queue）之上新增 adapter 层，输出「引用 + 六轴 attributes + 事件」的 ingest envelope；在 `mcp-server.mjs` 工具层以新增 `twinbox_*` 工具暴露能力，保持既有 9 个工具的入口形状不变；凭据集中加密存储。

## Technical Context

**Language/Version**: Python 3.10+（`twinbox_core/`），Node.js 18+（`mcp-server.mjs` 工具层）

**Primary Dependencies**: 现有依赖（imaplib 生态的 `imap_fetch.py`、`llm.py` 的 LLM 通路、PyYAML）；凭据加密优先使用系统 keyring 或 Python `cryptography`（Fernet 对称加密），选定前确认项目已依赖情况，否则以 stdlib + 本地密钥文件兜底并标注限制

**Storage**: 本地文件/SQLite 于 `~/.twinbox/`（沿用现有 queue 与配置约定，git-ignored）；归类轴配置在受追踪的 `config/extract-profiles.yaml`

**Testing**: `pytest`（`tests/test_extract.py` 现有套件扩展）+ `tests/mcp-smoke.mjs` 工具层冒烟

**Target Platform**: macOS / Linux 本机部署，MCP stdio 服务

**Project Type**: library + MCP tool server（单仓双语言薄封装）

**Performance Goals**: 单邮箱 1000 封批量 ingest ≤ 5 分钟（含 LLM 归类，可分页）

**Constraints**: 全文不出 twinbox 边界；单次工具输出 ≤ 可配置条数上限；IMAP 全程只读

**Scale/Scope**: v1 支持 ≤ 10 个邮箱账号、≤ 3 个公共邮箱并发同步

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Read-Only Mailbox**: 本 feature 不新增任何服务器写操作；公共邮箱接入复用只读 IMAP 通路。✅
- **II. Full Text Never Leaves twinbox**: ingest envelope schema 无 body/attachment 字段；摘要有界；LLM 抽取输出 schema 不含原文字段。✅
- **III. Classification Axes Stay in twinbox**: 六轴定义落在 `config/extract-profiles.yaml`，轴值对平台透明（opaque string）。✅
- **IV. Stable Tool Contract Surface**: 既有 9 个 `twinbox_*` 工具签名不动；新能力以新工具（如 `twinbox_ingest`、`twinbox_events`、`twinbox_accounts`）或 `data` 内新字段添加。✅
- **V. Credentials Never Leak**: vault 加密存储，输出只含存在性布尔值；spec/plan/tasks 与日志不含凭据。✅

无违规项，无需 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/001-everything-mail-adapter/
├── spec.md              # 需求与验收（已建）
├── plan.md              # 本文件
├── tasks.md             # 可执行任务清单（已建）
└── checklists/          # 按需由 speckit-checklist 生成
```

### Source Code (repository root)

```text
twinbox_core/
├── imap_fetch.py        # 只读 IMAP 拉取（复用，支持多账号参数化）
├── analyze.py           # 线程分析（复用）
├── extract.py           # 历史抽取（复用，扩展事件抽取）
├── pulse.py             # 周期同步调度（复用，多账号循环）
├── llm.py               # LLM 通路（复用，新增 envelope/event 输出 schema）
├── queue.py             # 本地队列（复用）
├── config.py            # 配置加载（扩展：多账号 + vault 引用）
├── adapter.py           # 新增：ingest envelope 组装、六轴归类映射、游标分页
├── events.py            # 新增：事件抽取（weekly_report / risk / plan_change）与去重
├── vault.py             # 新增：凭据加密存储（加解密、存在性布尔查询）
└── cli.py               # 扩展：ingest / events / accounts 子命令

mcp-server.mjs           # 扩展：注册 twinbox_ingest / twinbox_events / twinbox_accounts，
                         # 复用既有 spawn CLI 模式与 ok/data/error/recovery_tool 封装

config/
└── extract-profiles.yaml # 扩展：六轴归类定义与取值规则（受追踪、无秘密）

tests/
├── test_extract.py      # 复用扩展
├── test_adapter.py      # 新增：envelope schema、无全文断言、游标重放
├── test_vault.py        # 新增：加解密往返、无明文断言
└── mcp-smoke.mjs        # 扩展：新工具冒烟
```

**Structure Decision**: 单仓结构不变。所有新逻辑进入 `twinbox_core/` 新增模块（adapter / events / vault），CLI 新增子命令，`mcp-server.mjs` 只做薄封装注册新工具——与现有「Node 薄壳 + Python 核心」模式一致。归类规则属于配置（`config/extract-profiles.yaml`），不硬编码进任何下游。

## Design Notes

### ingest envelope 契约（v1）

```json
{
  "reference": {"account_id": "...", "message_id": "...", "thread_id": "...",
                 "subject": "...", "sender": "...", "date": "...", "excerpt": "...(≤280字)"},
  "attributes": {"person": ["..."], "thing": ["..."], "intent": "...",
                  "urgency": "...", "sensitivity": "...", "thread": "..."},
  "events": ["evt_..."],
  "cursor": "..."
}
```

- envelope 无 body / html / attachment 字段，schema 层面杜绝全文外泄。
- `attributes` 轴值由 `config/extract-profiles.yaml` 定义，平台按 opaque string 消费。
- `cursor` 为不透明字符串，内部编码账号 + UID 水位，支持重放与幂等。

### 凭据加密

- `twinbox_core/vault.py`：`~/.twinbox/vault.enc`，账号 ID → 密文条目。
- 主密钥优先级：系统 keyring > `~/.twinbox/.vault_key`（0600，git-ignored）。
- 读 API 只返回 `password_set: bool`；任何异常路径（含错误信息）不拼接凭据材料。

### 多账号

- `config.py` 扩展为账号列表模型；`pulse.py` 按账号循环同步；每条队列/ingest 记录携带 `account_id` 保证隔离与溯源。

### 事件抽取

- `events.py` 基于 `extract.py` 的 LLM 通路，输出固定 schema 的 EventRecord（稳定事件 ID = hash(account_id, message_id, event_type, 周期/键字段)），二次抽取按 ID 去重。
