# twinbox

给 Agent 用的线程级邮件智能。只读 IMAP，一次分析，直接给出紧急队列、待回复和周报。

接入 **MCP / Skill / CLI**。Python 核心、零二进制依赖——不是又一个 GUI 邮箱客户端。

## 它做什么

邮箱主人问「今天该回什么」「这周发生了什么」时，传统客户端给邮件列表；把整箱邮件丢给大模型，又贵又慢，还容易把正文泄漏到平台侧。

twinbox 走另一条路：本地抓信封和正文，**一次 LLM 调用**写成 `activity-pulse.json`，Agent 之后只读这份快照。

```
IMAP (imaplib) → fetch envelopes + bodies → LLM analysis (single pass) → activity-pulse.json
                                                                            ↓
MCP / Skill / CLI  →  python3 -m twinbox_core.cli <cmd> --json

Extract (isolated): IMAP SEARCH by date → keyword filter → runtime/queries/{id}/result.json
```

| 层 | 技术 | 说明 |
| --- | --- | --- |
| IMAP | Python `imaplib` | 只读，stdlib，零二进制 |
| 筛选 | 结构信号 + Semantic Pack | 候选约 45 线程，正文约 24 封，再交给模型 |
| 分析 | 单次 LLM 调用 | 一次产出紧急 / 待回复 / SLA 风险 / 周报 |
| 缓存 | `activity-pulse.json` | 查询读快照，不每次重跑模型 |
| 插件 | Node.js MCP stdio | Cursor / Claude Desktop / OpenClaw 同一套 `twinbox_*` 工具 |
| 配置 | `~/.twinbox/twinbox.json` | IMAP + LLM；凭据不出 git |

## 为什么值得用

### 一次分析，四类结果

意图、紧急度、待办、周报不再各开一轮模型。`run_analysis` 用同一套 prompt，一次 `call_llm`，按线程归一化写入 pulse：`daily_urgent`、`pending_replies`、`sla_risks`、`weekly_brief`。

### 先筛再问，不把整箱邮件塞进上下文

先用未读、新邮件、收件角色、时效等结构信号粗排，再按 Semantic Pack 的关注点做精选。规格常量是 **候选 45 / 正文 24**。模型只看一小批高密度线程，不是对整个邮箱做全量语义阅读。

配了 embedding 时，可用 pack 里的 `attention_hints` 做相似度加分；向量不可用则退回结构采样，分析链路不因此中断。

### Pulse 快照：问一次、用多次

`twinbox_latest_mail` / `twinbox_todo` / `twinbox_weekly` 读本地 pulse。缺快照才完整同步；超过新鲜度阈值（默认 4 小时）只标记 `staleness.stale=true`，不偷偷打 IMAP、不重跑 LLM。显式 `twinbox_sync --job quick-refresh` 才轻量刷新信封、复用上次分析结果。

### 分类规则可换，引擎不用改

人 / 事 / 意图 / 紧急度 / 敏感度 / 线程等分类轴，以及领域关注点，写在声明式 **Semantic Pack** 里，不写死在核心。换企业或个人场景，换 pack，不改引擎代码。

### 默认只读，全文不出平台

真实邮箱默认禁止发送、移动、删除、归档、打标；本地队列（完成 / 忽略 / 恢复）只改 twinbox 自己的状态。给平台侧的 ingest 只有稳定引用和 opaque 归类属性，不含正文和附件。邮箱主人自己的 MCP 会话可以看解码后的纯文本，那是给主人 Agent 的，不是给平台存档的。

## 和传统客户端、以及「直接丢给大模型」的差别

| 维度 | 传统邮件客户端 | 把整箱邮件丢给大模型 | twinbox |
| --- | --- | --- | --- |
| 权限 | 收发、移动、删除都有 | 取决于你把什么权限交给模型 | **只读 IMAP**；写操作须显式 Automation Policy |
| 形态 | GUI | 多轮对话 | 无 UI；**MCP 工具**接入 Cursor / Claude Desktop / OpenClaw |
| 输出 | 邮件列表 | 一段聊天回复 | 结构化 **紧急队列 / 待回复 / 周报** JSON（pulse） |
| 费用 | — | 逐封、多轮、反复读正文 | 预筛选 + **单次调用** + 快照复用 |
| 隐私 | 客户端各自为政 | 全文进对话、常进平台日志 | 全文留在 twinbox 边界内；平台侧只有引用 |
| 分类 | 手写过滤规则，或没有 | 每次重新解释你的偏好 | 可插拔 Semantic Pack |

相对「把邮件直接丢进对话」，省的是结构，不是口头上的更快：

1. **少 token**：结构粗排 + 关注点精选，交给模型的是约 45 条候选、24 封正文，不是整箱原文。
2. **少调用**：紧急 / 待回复 / 周报合并进一次 prompt，不为四个问题开四轮。
3. **少重复**：查询走 pulse；过期只标陈旧；`quick-refresh` 不跑 LLM。
4. **少用模型做检索**：候选排序走本地结构信号（可选自托管 embedding + 余弦），不把「找哪几封值得看」交给大模型逐封判断。

仓库里没有公开 latency benchmark；上面是流水线设计上的省，不是测出来的毫秒数。

## Quick Start

```bash
# 1. Clone
git clone https://github.com/caapapx/twinbox ~/.openclaw/skills/twinbox
cd ~/.openclaw/skills/twinbox

# 2. Install
pip install --user .

# 3. Configure IMAP (in OpenClaw skill env)
# Set: IMAP_HOST, IMAP_PORT, IMAP_LOGIN, IMAP_PASS, MAIL_ADDRESS

# 4. Verify
python3 -m twinbox_core.cli setup --json
```

## MCP stdio server

A real MCP stdio server is included so Cursor / Grok Bot / Claude Desktop can use twinbox as a local connector. It wraps `python3 -m twinbox_core.cli <cmd> --json`.

### Add as a local MCP connector

```json
{
  "mcpServers": {
    "twinbox": {
      "command": "node",
      "args": ["/absolute/path/to/twinbox/mcp-server.mjs"],
      "cwd": "/absolute/path/to/twinbox",
      "env": {
        "IMAP_HOST": "imap.example.com",
        "IMAP_PORT": "993",
        "IMAP_ENCRYPTION": "tls",
        "IMAP_LOGIN": "you@example.com",
        "IMAP_PASS": "...",
        "MAIL_ADDRESS": "you@example.com"
      }
    }
  }
}
```

- `command` / `args`: launch the stdio server; use absolute paths.
- `cwd`: repo root so `node` can resolve `twinbox_core/` via `PYTHONPATH` (or install the package and omit `cwd`).
- `env`: IMAP credentials and owner email. `TWINBOX_CODE_ROOT` and `TWINBOX_STATE_ROOT` are optional; `LLM_API_KEY` / `LLM_MODEL` / `LLM_API_URL` are read by the Python CLI when needed.

### Run locally

```bash
npm install
node mcp-server.mjs
```

The server listens on stdio and speaks MCP. Baseline tools stay stable; accounts / ingest / events and action-proposal tools are additive.

### Tools


| 工具                         | 功能                           |
| -------------------------- | ---------------------------- |
| `twinbox_sync`             | 邮件同步 + LLM 分析                |
| `twinbox_latest_mail`      | 最新邮件摘要（缺失时自动同步；过期只标 staleness） |
| `twinbox_todo`             | 紧急 / 待回复队列                   |
| `twinbox_weekly`           | 周报（当前 sync 产物）               |
| `twinbox_extract`          | 历史 / 定向抽取（时间范围 + 关键词，不触发 sync） |
| `twinbox_thread_inspect`   | 查看 / 搜索线程                    |
| `twinbox_queue_action`     | 标记完成 / 忽略 / 恢复               |
| `twinbox_status`           | 邮箱健康检查 + pipeline            |
| `twinbox_setup`            | 初始配置                         |
| `twinbox_onboard`          | 最小问卷写入 Semantic Pack         |
| `twinbox_action_proposals` | 策略 dry-run 提案（无 SMTP）        |
| `twinbox_action_review`    | 本地确认 / 拒绝提案                  |
| `twinbox_accounts`         | 多账号 list / add / remove / 设默认 |
| `twinbox_ingest`           | 引用式 ingest（无正文）              |
| `twinbox_events`           | 事件记录                         |

### Extract CLI

```bash
python3 -m twinbox_core.cli extract --profile weekly_report --since 2025-06-01 --json
python3 -m twinbox_core.cli extract --since 2025-01-01 --folder INBOX --folder Sent \
  --subject-contains "周报,Weekly" --weekdays fri,sat,sun --json
```

Presets: [`config/extract-profiles.yaml`](config/extract-profiles.yaml)

### Local scheduler (host crontab)

Do not start an in-process daemon. Drive due jobs from cron:

```cron
0 12 * * *  TWINBOX_STATE_ROOT=/path/to/state python3 -m twinbox_core.cli schedule run-due --json
0 2 * * *   TWINBOX_STATE_ROOT=/path/to/state python3 -m twinbox_core.cli schedule run-due --json
```

See `config/schedules.yaml` and `specs/007-local-scheduler/`.

## Dependencies

- Python >= 3.11
- PyYAML
- Node.js (MCP host)
- Optional extras: openpyxl, python-docx (material import only)

## TODO

- [ ] Claw Hub manifest for one-click deploy
- [ ] crontab 连续 3 天观察 `stale=0`（见 `007` T010）
- [ ] Embedding rerank phase 2 / zvec storage upgrade
- [ ] `004` 周报运营

## License

Apache-2.0
