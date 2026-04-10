# twinbox

线程级邮件智能 — OpenClaw Skill。只读 IMAP，分析紧急度/待回复/周报。

~2,000 行 Python + 8 个 OpenClaw 工具。零二进制依赖。

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
OpenClaw plugin → python3 -m twinbox_core.cli <cmd> --json ← 8 tools
```

| 层 | 技术 | 说明 |
|----|------|------|
| IMAP | Python `imaplib` | 零二进制，stdlib |
| 分析 | 单次 LLM 调用 | 合并 intent+urgent+pending+weekly |
| 插件 | Node.js (`@sinclair/typebox`) | 8 个 OpenClaw 工具 |
| 配置 | `~/.twinbox/twinbox.json` | IMAP + LLM (从 OpenClaw 导入) |

## Tools (8)

| 工具 | 功能 |
|------|------|
| `twinbox_sync` | 邮件同步 + LLM 分析 |
| `twinbox_latest_mail` | 最新邮件摘要（自动同步） |
| `twinbox_todo` | 紧急/待回复队列 |
| `twinbox_weekly` | 周报 |
| `twinbox_thread_inspect` | 查看/搜索线程 |
| `twinbox_queue_action` | 标记完成/忽略/恢复 |
| `twinbox_status` | 邮箱健康检查 |
| `twinbox_setup` | 初始配置 |

## Dependencies

- Python >= 3.11
- PyYAML
- Node.js (OpenClaw gateway)

## TODO

- [ ] Multi-folder support (Sent, Drafts)
- [ ] Claw Hub manifest for one-click deploy
- [ ] OpenClaw native cron integration
- [ ] Profile/calibration onboarding flow

## License

MIT
