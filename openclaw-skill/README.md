# OpenClaw Skill Development

这个目录用于单独推进 `OpenClaw` 托管形态下的 Twinbox skill 包开发，避免继续和 `.claude/` 本地代理 skill 混在一起。

## 定位

- `SKILL.md`：仓库根上的 OpenClaw manifest / shared metadata root
- `.claude/`：Claude Code / Opencode 本地代理 skill 与命令层
- `openclaw-skill/`：OpenClaw 托管 skill 的开发、部署、验证入口

## 当前判断

- Twinbox 对 OpenClaw 的基础契约已经开始成形，但还没有到“完整托管 runtime 已接通”的状态
- 当前更像是：
  - 有 manifest
  - 有 preflight 接口
  - 有 schedule metadata 设计
  - 有 stable CLI / orchestration contract
  - 但 listener / action / heartbeat / 托管调度的真实接入还没走完

## Source Of Truth

- [../SKILL.md](../SKILL.md)
- [../docs/ref/cli.md](../docs/ref/cli.md)
- [../docs/ref/orchestration.md](../docs/ref/orchestration.md)
- [../docs/ref/runtime.md](../docs/ref/runtime.md)
- [../docs/ref/scheduling.md](../docs/ref/scheduling.md)
- [../docs/ref/skill-authoring-playbook.md](../docs/ref/skill-authoring-playbook.md)

## 本目录职责

- 单独梳理 OpenClaw skill 包方案
- 单独梳理部署、升级、验证、回滚
- 单独跟踪 OpenClaw 尚未验证的问题
- 为后续独立导出 skill package 预留清晰入口

## 当前文件

- [DEPLOY.md](./DEPLOY.md)：OpenClaw skill 部署与验证说明
