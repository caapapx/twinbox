# CLAUDE.md

## 项目概述

twinbox 是一个以线程为中心的邮件 Copilot 基础设施。
核心路径：read-only → draft → controlled send。

## 关键路径

- 架构：docs/architecture.md
- 核心重构计划：docs/plans/core-refactor-plan.md
- 任务命令规范：docs/specs/task-facing-cli.md
- 方案：docs/plans/
- 规范：docs/specs/
- 脚本：scripts/*.sh

## 开发约束

1. 只使用 master 分支
2. 提交信息格式：`type: short description`
3. Phase 1-4 只读，禁止 send/move/delete/archive/flag
4. 新增方案文档放 docs/plans/
5. gastown 是符号链接，不要修改其内容

## 文档索引与协作规则

详见 AGENTS.md：
- 文档索引规则
- 核心文档入口
- Gastown 集成（可选）
- Issue tracking with bd
- Landing the Plane 流程

