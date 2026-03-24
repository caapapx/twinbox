# CLAUDE.md

## 项目概述

twinbox 是一个以线程为中心的邮件 Copilot 基础设施。
核心路径：read-only → draft → controlled send。

## 关键路径

- 文档入口：docs/README.md
- 架构：docs/ref/architecture.md
- 核心重构计划：docs/core-refactor.md
- 任务命令规范：docs/ref/cli.md
- 参考文档：docs/ref/
- 指南：docs/guide/
- 脚本：scripts/*.sh

## 开发约束

1. 只使用 master 分支
2. 提交信息格式：`type: short description`
3. Phase 1-4 只读，禁止 send/move/delete/archive/flag
4. 新增文档先查 `docs/README.md`，优先合并，避免扩目录

## 文档索引与协作规则

详见 AGENTS.md：
- 文档索引规则
- 核心文档入口
- 协作约束
