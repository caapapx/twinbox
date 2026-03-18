# CLAUDE.md

## 项目概述

twinbox 是一个以线程为中心的邮件 Copilot 基础设施。
核心路径：read-only → draft → controlled send。

## 关键路径

- 架构：docs/architecture.md
- 方案：docs/plans/
- 规范：docs/specs/
- 脚本：scripts/*.sh
- 类型合约：agent/custom_scripts/types.ts
- 策略配置：config/policy.default.yaml
- 角色配置：config/profiles/

## 文档索引规则

见 AGENTS.md 的"文档索引规则"章节。

## 开发约束

1. 只使用 master 分支
2. 提交信息格式：`type: short description`
3. Phase 1-4 只读，禁止 send/move/delete/archive/flag
4. 新增方案文档放 docs/plans/
5. gastown 是符号链接，不要修改其内容
