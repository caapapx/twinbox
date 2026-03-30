---
name: twinbox
description: 快速查看邮箱状态：最新邮件、待办、周报。可在任何会话中通过 /twinbox 调用。
invocation: /twinbox
---

# Twinbox - 全局邮箱助手

快速邮箱查询工具，可在任何 OpenClaw 会话中使用。

## 用法

```
/twinbox [命令]
```

## 常用命令

- `/twinbox` 或 `/twinbox latest` - 查看最新邮件
- `/twinbox todo` - 查看待办和紧急事项
- `/twinbox weekly` - 查看本周简报
- `/twinbox status` - 检查邮箱和系统状态

## 实现

执行对应的 twinbox CLI 命令并返回结果。
