# CLAUDE.md

## 项目概述

twinbox 是轻量级 OpenClaw 邮件智能 Skill。只读 IMAP → 线程分析 → 紧急/待回复/周报输出。

## 关键路径

| 用途 | 路径 |
|------|------|
| Skill 定义 | `SKILL.md` |
| Python 核心 | `twinbox_core/` |
| CLI 入口 | `twinbox_core/cli.py` |
| OpenClaw 插件 | `register-tools.mjs` |
| 配置 | `~/.twinbox/twinbox.json` |

## 开发约束

1. **分支**：`openclaw-skill` 为轻量版主分支。
2. **提交信息**：`type: short description`。
3. **只读**：禁止 send / move / delete / archive / flag。
4. **验证与 Git**：默认不自动 commit / push。
5. **调试**：修改 `twinbox_core` 后直接运行 `python3 -m twinbox_core.cli <cmd> --json`，无需重启 daemon。
