---
name: twinbox
description: >-
  邮件智能技能。调用 twinbox_* 工具查看邮件、待办、周报。
  先调工具，再写文字摘要。禁止只说不调。
  最新邮件：twinbox_latest_mail（自动同步）。
  待办/紧急：twinbox_todo。周报：twinbox_weekly。
  搜索线程：twinbox_thread_inspect。
  标记完成/忽略：twinbox_queue_action。
  邮箱状态：twinbox_status。初始化：twinbox_setup。
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

# twinbox

线程级邮件智能。只读 IMAP，分析线程紧急度/待回复/周报摘要。

## 工具表

| 用户意图 | 工具 |
|----------|------|
| 最新邮件 / 今日摘要 | `twinbox_latest_mail` |
| 待办 / 紧急 / 待回复 | `twinbox_todo` |
| 周报 | `twinbox_weekly` |
| 查看/搜索线程 | `twinbox_thread_inspect` |
| 标记完成/忽略/恢复 | `twinbox_queue_action` |
| 同步邮件数据 | `twinbox_sync` |
| 邮箱健康检查 | `twinbox_status` |
| 初始配置 | `twinbox_setup` |

## 规则

1. 先调工具，再用文字总结输出。禁止纯文字无工具调用。
2. `twinbox_latest_mail` 在数据缺失时自动同步，不要说"先同步再查看"。
3. `twinbox_queue_action` 后确认操作结果。
4. 默认只读，不发送/删除/归档邮件。
