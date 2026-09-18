---
name: twinbox
description: >-
  Twinbox MCP email skill. Call the matching twinbox_* MCP tool first and then
  summarize its result. Covers latest mail, todo, weekly briefs, sync,
  thread inspection, historical extraction, local queue actions, status, and setup.
  The real mailbox is read-only by default.
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
| 初始配置 | `twinbox_setup` |
| 账号管理 | `twinbox_accounts`（list/add/remove/`set-default`；vault 凭据；仅 `password_set`） |
| 引用式 ingest | `twinbox_ingest` |
| 事件记录 | `twinbox_events` |

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
8. 不要使用 MCP 改造前的旧 CLI 命令体系；在 `master` 上只调用 `twinbox_*` MCP 工具。

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
