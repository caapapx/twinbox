# twinbox

线程级邮件智能 — 只读 IMAP，分析紧急度/待回复/周报。默认主干是 **`master`**（MCP Skill / CLI）。旧大栈在 `archive/openclaw-monolith`。

~2,000 行 Python + 9 个 OpenClaw 工具。零二进制依赖。

## Quick Start

```bash
# 1. Clone
git clone https://github.com/user/twinbox ~/.openclaw/skills/twinbox
cd ~/.openclaw/skills/twinbox

# 2. Install
pip install --user .

# 3. Configure IMAP (in OpenClaw skill env)
# Set: IMAP_HOST, IMAP_PORT, IMAP_LOGIN, IMAP_PASS, MAIL_ADDRESS

# 4. Verify
python3 -m twinbox_core.cli setup --json
```

## Architecture

```
IMAP (imaplib) → fetch envelopes + bodies → LLM analysis (single pass) → activity-pulse.json
                                                                            ↓
OpenClaw plugin → python3 -m twinbox_core.cli <cmd> --json ← 9 tools

Extract (isolated): IMAP SEARCH by date → keyword filter → runtime/queries/{id}/result.json
```

| 层 | 技术 | 说明 |
|----|------|------|
| IMAP | Python `imaplib` | 零二进制，stdlib |
| 分析 | 单次 LLM 调用 | 合并 intent+urgent+pending+weekly |
| 插件 | Node.js (`@sinclair/typebox`) | 9 个 OpenClaw 工具 |
| 配置 | `~/.twinbox/twinbox.json` | IMAP + LLM (从 OpenClaw 导入) |

## MCP stdio server

A real MCP stdio server is included so Cursor / Grok Bot / Claude Desktop can use twinbox as a local connector. It exposes the same 9 tools as the OpenClaw plugin by wrapping `python3 -m twinbox_core.cli <cmd> --json`.

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

The server listens on stdio and speaks MCP. Core 9 tools stay stable; additive tools (`twinbox_onboard`, `twinbox_action_proposals`, `twinbox_action_review`) are optional.

### Tools (core 9 + additive)

| 工具 | 功能 |
|------|------|
| `twinbox_sync` | 邮件同步 + LLM 分析 |
| `twinbox_latest_mail` | 最新邮件摘要（过期/缺失时自动同步） |
| `twinbox_todo` | 紧急/待回复队列 |
| `twinbox_weekly` | 周报（当前 sync 产物） |
| `twinbox_extract` | 历史/定向抽取（时间范围 + 关键词，不触发 sync） |
| `twinbox_thread_inspect` | 查看/搜索线程 |
| `twinbox_queue_action` | 标记完成/忽略/恢复 |
| `twinbox_status` | 邮箱健康检查 + pipeline |
| `twinbox_setup` | 初始配置 |
| `twinbox_onboard` | 最小问卷写入 Semantic Pack |
| `twinbox_action_proposals` | 策略 dry-run 提案（无 SMTP） |
| `twinbox_action_review` | 本地确认/拒绝提案 |

### Extract CLI

```bash
python3 -m twinbox_core.cli extract --profile weekly_report --since 2025-06-01 --json
python3 -m twinbox_core.cli extract --since 2025-01-01 --folder INBOX --folder Sent \
  --subject-contains "周报,Weekly" --weekdays fri,sat,sun --json
```

Presets: [`config/extract-profiles.yaml`](config/extract-profiles.yaml)

### Local scheduler (site crontab)

Do not start an in-process daemon. Drive due jobs from cron:

```cron
30 8 * * *  TWINBOX_STATE_ROOT=/path/to/state python3 -m twinbox_core.cli schedule run-due --json
0 2 * * *   TWINBOX_STATE_ROOT=/path/to/state python3 -m twinbox_core.cli schedule run-due --json
```

See `config/schedules.yaml` and `specs/007-local-scheduler/`.

## Dependencies

- Python >= 3.11
- PyYAML
- Node.js (MCP / host agent host)
- Optional extras: openpyxl, python-docx (material import only)

## TODO

- [ ] Claw Hub manifest for one-click deploy
- [ ] site crontab 连续 3 天观察 `stale=0`（见 `007` T010；条目已挂）
- [ ] Embedding rerank phase 2 / zvec storage upgrade
- [ ] `004` 周报运营

## License

MIT
