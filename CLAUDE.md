# CLAUDE.md

面向助手与自动化工具的**精简入口**。目录索引、完整文档链接与协作细则以 **`AGENTS.md`** 为准；两文件冲突时以 **AGENTS.md** 为单一事实来源。

## 项目概述

twinbox 是以线程为中心的邮件 Copilot 基础设施。核心路径：read-only → draft → controlled send。

## 关键路径（速查）

| 用途 | 路径 |
|------|------|
| 文档入口 | `docs/README.md` |
| 架构 | `docs/ref/architecture.md` |
| 当前实现切片（daemon / Go / 模拟邮箱） | `docs/ref/daemon-and-runtime-slice.md` |
| CLI | `docs/ref/cli.md` |
| 路线与待办 | `ROADMAP.md` |
| 缺陷与修复记录 | `BUGFIX.md`（根目录，含 OpenClaw 排障摘要） |
| 参考 / 脚本 | `docs/ref/`、`scripts/*.sh` |

## 开发约束（摘要）

1. **分支**：主线 `master`；feature 独立分支（如 `dev-go`），合并后删除该分支。
2. **提交信息**：`type: short description`。
3. **Phase 1–4**：只读；禁止 send / move / delete / archive / flag。
4. **文档**：新增前先查 `docs/README.md`，优先合并进现有文件；入口级路径变更须更新索引（见 AGENTS.md）。
5. **验证与 Git**：默认**不自动** `git commit` / `git push`；用户明确要求时再执行。相关校验通过后若要提交，仍遵守提交信息与粒度约定；禁止对共享分支 `push --force`。细则见 AGENTS.md。
6. **OpenClaw / Skill**：改 CLI、核心行为或 Tool 时须同步 `SKILL.md` 并部署（步骤见 AGENTS.md）。

## Feature 分支（如 dev-go）

合并回 `master` 后删除 feature 分支；合并前可正常提交与推送。事实以 `docs/ref/daemon-and-runtime-slice.md` 与代码为准，勿被未更新的旧文档否定已合并行为。

## 全文约定

- 目录与命名：`AGENTS.md` → 文档索引规则  
- 核心文档入口与可发现性：`AGENTS.md`  
- 协作、Git、Skill 同步：`AGENTS.md` → 协作约束
