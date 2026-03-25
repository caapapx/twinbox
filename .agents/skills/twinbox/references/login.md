# Login & Mailbox Reference

> Distilled from `docs/ref/cli.md` (mailbox preflight). Use with the twinbox skill when interpreting `login_stage` or env setup.

## 登录状态机

```
unconfigured → validated → mailbox-connected
```

| 阶段 | 含义 | 触发条件 |
|------|------|---------|
| `unconfigured` | 缺少必需 env | 任意必需字段缺失 |
| `validated` | env 完整，config 已渲染 | IMAP 仍未通过 |
| `mailbox-connected` | IMAP 只读验证成功 | 读取 envelope list 成功 |

## 必需环境变量

```
IMAP_HOST, IMAP_PORT, IMAP_LOGIN, IMAP_PASS
SMTP_HOST, SMTP_PORT, SMTP_LOGIN, SMTP_PASS
MAIL_ADDRESS
```

## 常用默认值（未在 `.env` 中设置时可由工具链补全）

```
MAIL_ACCOUNT_NAME=myTwinbox
MAIL_DISPLAY_NAME={MAIL_ACCOUNT_NAME}
IMAP_ENCRYPTION=tls
SMTP_ENCRYPTION=tls
```

## Preflight 命令

```bash
twinbox mailbox preflight --json
```

完整 MailboxPreflightResult schema 见 `docs/ref/cli.md` → MailboxPreflightResult。

## 只读边界

- Phase 1-4 仅做 IMAP 读取，不发送/移动/删除任何邮件
- SMTP 在只读模式下返回 `warn` + `smtp_skipped_read_only`，不阻塞 phase 运行
