# CLAUDE.md

## 项目概述

twinbox 是一个以线程为中心的邮件 Copilot 基础设施。
核心路径：read-only → draft → controlled send。

## 关键路径

- 文档入口：docs/README.md
- 架构：docs/ref/architecture.md
- 核心重构计划：docs/core-refactor.md
- **当前实现切片（daemon / Go 薄壳 / 模拟邮箱种子）**：docs/ref/daemon-and-runtime-slice.md
- 任务命令规范：docs/ref/cli.md
- 参考文档：docs/ref/
- 指南：docs/guide/
- 脚本：scripts/*.sh

## 开发约束

1. 主线为 `master`；feature 在独立分支开发（如 `dev-go`），合并后删除该分支
2. 提交信息格式：`type: short description`
3. Phase 1-4 只读，禁止 send/move/delete/archive/flag
4. 新增文档先查 `docs/README.md`，优先合并，避免扩目录
5. 新增/移动入口级文档时同步更新索引（`docs/README.md`、`AGENTS.md` 核心文档入口或子目录 README）；细则见 AGENTS.md
6. 约定验证（如相关 pytest / 指定 smoke）高置信度通过后：应 `git commit`；环境允许且未要求仅本地时应 `git push`；禁止对共享分支 `push --force`；细则见 AGENTS.md
7. **Skill 同步约束**：新增或修改 CLI 命令、核心功能或 Tool 时，必须同步更新 `SKILL.md` 并部署到 OpenClaw（详见 AGENTS.md 协作约束）。

## 开发约束（dev-go 或大重构 feature 分支）

用于 Python daemon + Go 薄客户端等运行时切片时：合并回 `master` 后删除 feature 分支；合并前可提交与推送。文档以 `docs/ref/daemon-and-runtime-slice.md` 与代码为准，勿被未更新的历史段落否定已合并行为。

## 文档索引与协作规则

详见 AGENTS.md：
- 文档索引规则
- 核心文档入口
- 协作约束
