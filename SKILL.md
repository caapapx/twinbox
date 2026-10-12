---
name: twinbox
description: >-
  Twinbox MCP email skill. Call the matching twinbox_* MCP tool first and then
  summarize its result. Covers latest mail, todo, weekly briefs, sync,
  thread inspection, historical extraction, local queue actions, status, and setup.
  The real mailbox is read-only by default; outbound mail only via
  twinbox_draft_send -> human approval -> twinbox_send (TWINBOX_SEND_ENABLED=1).
metadata:
  openclaw:
    requires:
      env: [IMAP_HOST, IMAP_PORT, IMAP_LOGIN, IMAP_PASS, MAIL_ADDRESS]
    primaryEnv: IMAP_LOGIN
    login:
      mode: password-env
      runtimeRequiredEnv: [IMAP_HOST, IMAP_PORT, IMAP_LOGIN, IMAP_PASS, MAIL_ADDRESS]
      optionalDefaults:
        IMAP_ENCRYPTION: tls
---

# twinbox MCP skill

Twinbox is a thread-level email assistant exposed as a local MCP stdio server.
Call tools by their exact `twinbox_*` names; these are MCP tools, not shell
commands.

## Tool table

| 用户意图 | MCP 工具 |
|---|---|
| 最新邮件 / 今日摘要 | `twinbox_latest_mail`（可选 `unread_only`、`account_id`；省略则用配置默认箱；数据缺失时自动同步） |
| 待办 / 紧急 / 待回复 | `twinbox_todo`（可选 `account_id`） |
| 当前周报 | `twinbox_weekly`（可选 `account_id`） |
| 手动同步/刷新分析 | `twinbox_sync`（`job=daytime-sync` 或 `nightly-full`；省略 `account_id` 则同步全部） |
| 查看/搜索线程 | `twinbox_thread_inspect`（必填 `query`；可选 `account_id`） |
| 标记完成/忽略/恢复 | `twinbox_queue_action`（`action`、`thread_key`，可选 `reason`、`account_id`） |
| 历史/关键词抽取 | `twinbox_extract`（日期、文件夹、关键词、profile 等过滤器；可选 `account_id`） |
| 邮箱健康检查 | `twinbox_status`（可选 `account_id`；含 freshness / recent runs） |
| 初始配置 | `twinbox_setup`（必填 `weknora_enabled` true/false；再次调用即切换该开关；同时校验 IMAP/LLM） |
| 账号管理 | `twinbox_accounts`（list/add/remove/`set-default`；vault 凭据；仅 `password_set`） |
| 引用式 ingest | `twinbox_ingest` |
| 事件记录 | `twinbox_events` |
| 动态分类目录 / 事项分类 / 按需证据 | `twinbox_semantics`（`catalog/list/get`；证据默认不展开） |
| 策略动作提案 / 取得人工确认 token | `twinbox_action_proposals`（只生成本地 dry-run draft；不写邮箱） |
| 拒绝 / 过期 / 确认某条动作提案 | `twinbox_action_review`（`confirm` 必须带上一轮人工给出的 `confirmation_token`；仅改变本地状态） |
| 分类纠正、人工确认、执行回执 | `twinbox_feedback`（需本地管理员 source grant；不修改邮箱） |
| 起草待发邮件（不发送） | `twinbox_draft_send`（`to`/`cc`/`bcc`/`subject`/`text_body`/`html_body`/`from_name`；写 `~/.twinbox/runtime/outbox/<id>.{eml,json}`，返回预览 + 30 分钟一次性 `confirmation_token`） |
| 存进邮箱草稿箱（不发送） | `twinbox_save_draft`（`draft_id`；IMAP APPEND 到 `Drafts`，`\\Draft`，按 Message-ID 去重；不需 token/开关） |
| **真实发信** | `twinbox_send`（`draft_id` + `confirm=true` + `confirmation_token`；需 `TWINBOX_SEND_ENABLED=1`；SMTP 后 APPEND 到 `Sent Items`（`\\Seen`）并按 Message-ID 校验） |

## 规则

1. 先调用对应 MCP 工具，再根据返回结果写文字摘要，禁止纯文字回答。
2. `twinbox_latest_mail` 在 `activity-pulse.json` 缺失时会自动同步，不要要求用户先同步。
3. 当前周报用 `twinbox_weekly`；历史周报或按关键词检索用
   `twinbox_extract`，后者不会触发日常 sync。
4. 用户确认队列项完成、忽略或恢复时调用 `twinbox_queue_action`，并确认工具返回结果。
5. 默认只读真实邮箱；`twinbox_queue_action` 只修改 Twinbox 本地队列可见性，
   不会发送、删除、归档或把邮箱标为已读。
6. 未读状态跟随**上次 sync** 的 IMAP FLAGS；Outlook/手机标已读后，用
   `twinbox_sync(job="quick-refresh")` 回刷，不要为开箱体感跑 daytime LLM。
7. 卡片上的 `evidence_basis=insufficient` 表示责任未证实，不要说成「你必须回复」；点开 `twinbox_thread_inspect` 才看证据。
8. `twinbox_feedback` 只接受本地 `config/source-grant.json` 已绑定的 actor/kind/evidence；聊天参数不能自报授权，回执成功也不等于业务完成或邮件已归档。
9. `twinbox_action_proposals` 返回 `card_payload.interaction.must_stop_agent_turn=true` 时，**必须结束当前 Agent 工具回合**，向人说明 draft、风险和短时 token；不得在同一回合调用 `twinbox_action_review(confirm)`，不得猜测、生成或代填 token。仅收到后续人类消息中的原样 token 时，才可调用 confirm。token 过期、重放、与 draft hash 不匹配时保持不确认；确认也只会得到本地 `blocked_read_only` 状态，绝不写邮箱或外发。
10. 不要使用 MCP 改造前的旧 CLI 命令体系；在 `master` 上只调用 `twinbox_*` MCP 工具。
11. 发信唯一路径：`twinbox_draft_send` → 把完整预览（收件人/抄送/主题/正文）给人看并**结束本回合** → 人在后续消息明确同意 → `twinbox_send(draft_id, confirm=true, confirmation_token)`。不得同回合发送、不得代填或猜 token；已发/发送中草稿拒绝重发。
12. 发信护栏：默认关闭，`TWINBOX_SEND_ENABLED=1`（或 `twinbox.json` `send.enabled: true`）才放行；可选收件域白名单 `TWINBOX_SEND_ALLOWED_DOMAINS` / `send.allowed_domains`；Sent 文件夹 `TWINBOX_SENT_FOLDER`（默认 `Sent Items`），草稿箱 `TWINBOX_DRAFTS_FOLDER`（默认 `Drafts`）。凭据读 Himalaya config（`~/.twinbox/runtime/himalaya/config.toml`，应为 0600），从不输出密码。
13. 用户只要“存草稿”时用 `twinbox_save_draft`，不要调用 `twinbox_send`。`twinbox_send` 返回 `sent_items_verified=false` 时如实告知，不要重发。

## extract 示例

历史周报：

```text
twinbox_extract(profile="weekly_report", since="2025-06-01")
```

自定义关键词：

```text
twinbox_extract(
  since="2025-01-01",
  folders=["INBOX", "Sent"],
  subject_contains="合同,Contract",
  weekdays="",
)
```

MCP server 的 stdio 注册方式和环境变量见仓库根目录 `README.md`。

唯一检出（canonical）：`/Users/caapap/iflytek/twinbox`（`node mcp-server.mjs`，`TWINBOX_CODE_ROOT` 同目录，`TWINBOX_PYTHON=.venv/bin/python`；CLI `~/.local/bin/twinbox` → `bin/twinbox`）。旧 `~/fun/twinbox` 已于 2026-10-12 删除。
