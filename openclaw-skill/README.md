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

## 最近实测状态

- 本机已在原生 npm OpenClaw 上完成一轮托管 skill 与 Twinbox 联调验证
- 当前原生 CLI 安装方式已确认可用：
  - `npm install -g openclaw@latest`
- 当前原生默认目录按平台约定使用：
  - `~/.openclaw/openclaw.json`
  - `~/.openclaw/skills/`
  - `~/.openclaw/workspace/`
- 已确认可复用迁移的内容包括：
  - managed skill：`twinbox`
  - OpenClaw 模型配置：`xfyun-mass/astron-code-latest`
  - workspace 启动文件：`AGENTS.md`、`SOUL.md`、`HEARTBEAT.md` 等
  - identity / devices / memory 等宿主状态
- 已确认不应直接迁移旧的 `agents/main/sessions/`：
  - 原因不是文件损坏，而是旧 `skillsSnapshot` 可能冻结住 skill 注入结果
  - 这类文件应备份保留，但不应作为 native 默认启动状态直接恢复

## 当前 Native Smoke

- `openclaw config validate`：已通过
- `openclaw skills info twinbox`：已显示 `Ready`
- `openclaw tui`：已实际连上 Gateway
- `openclaw agent --agent main ...`：已成功完成一次原生 agent turn
- `twinbox mailbox preflight --json`：已在宿主机直接成功执行
- `openclaw agent --agent twinbox ...`：在显式写入 `skills.entries.twinbox.env` 并重启 Gateway 后，新的 `agent:twinbox:main` session 已确认把 `twinbox` 注入到 `systemPromptReport.skills.entries`

这说明当前原生 OpenClaw 至少已经拿到：

- 正常 CLI 安装
- 默认目录下的 managed skill 识别
- native 配置可校验
- TUI 连通性可验证
- Gateway 到模型提供方的真实调用可验证
- Twinbox 宿主 CLI / mailbox preflight 可验证
- 但 Twinbox 的 code root / state root 仍需在 native 部署时显式初始化，否则 workspace 视角可能把 `.env` 解析错位
- 2026-03-25 起，Twinbox 还补了 `twinbox task ...` 这层薄任务入口，专门承接 OpenClaw 常见 prompt：
  - `twinbox task latest-mail --json`
  - `twinbox task todo --json`
  - `twinbox task progress QUERY --json`
  - `twinbox task mailbox-status --json`

但也新增了一条明确边界：

- agent 在自然语言提示下“自己执行 Twinbox preflight”目前仍不可靠，不能把它当成 `preflightCommand` 或 skill command 已闭环的证据
- **分层设计**（详见 [DEPLOY.md](./DEPLOY.md) §2、§3.8）：用户态配置主路径是在 OpenClaw **`twinbox` 会话**里走 `twinbox onboarding …` 对话引导，长耗时刷新由 `twinbox-orchestrate schedule` / bridge / cron 在**后台**执行；**宿主态一次性接线**（skill 同步、Gateway reload、`skills.entries.twinbox.env`、roots init、可选 bridge/timer）仍需按 DEPLOY **§3** 在 shell/运维侧完成，不能假设仅靠聊天就能写入 `openclaw.json` 或安装 systemd

## 推荐使用策略

如果目标是“稳定使用 Twinbox”，当前不建议继续把 Twinbox 问题都扔给默认 `main` 会话。

更稳的结构是：

- `main` agent：保留给通用聊天
- `twinbox` agent：专门处理 Twinbox
- `system-event / cron`：只触发宿主 bridge，不进入人工聊天 session

原因不是抽象架构偏好，而是当前实测已经证明：

- `session` 会冻结自己的 `skillsSnapshot`
- `openclaw skills info twinbox = Ready` 不等于当前会话 prompt 已包含 `twinbox`
- 如果 Gateway run 没拿到 Twinbox 所需 env，该 skill 会在 run 级直接被过滤掉

所以稳定性的关键有三条：

1. Twinbox 邮箱 env 写入 `~/.openclaw/openclaw.json` 的 `skills.entries.twinbox.env`
2. Twinbox 问题固定走专用 `twinbox` agent
3. skill / env 变更后，用新 session 验证，不继续复用旧快照
4. 对常见任务优先走 `twinbox task ...`，不要继续依赖“自由自然语言 + 模型自己选命令”

## 初始化重点

**从零安装与 cwd 约定以 [DEPLOY.md](./DEPLOY.md) §3 为准**（本文下方命令假设当前在 `openclaw-skill/`）。

native OpenClaw 部署不要只迁 `~/.openclaw`，还要初始化 Twinbox roots：

```bash
bash ../scripts/install_openclaw_twinbox_init.sh
```

它会默认写入：

- `~/.config/twinbox/code-root`
- `~/.config/twinbox/state-root`
- `~/.config/twinbox/canonical-root`（legacy alias）

否则 Twinbox 命令如果从 `~/.openclaw/workspace` 发起，可能会把 workspace 当成 state root，继而错误地去找 `~/.openclaw/workspace/.env`，表现成“邮箱 env 未配置”。

推荐语义：

- OpenClaw skill env / process env 是一等配置源
- `state root/.env` 是本地开发与自托管 fallback
- 当前仓库仍默认 `code root == state root`，但这只是当前实例布局，不是通用标准

但这仍不等价于：

- `metadata.openclaw.schedules` 已被平台自动消费
- 日内调度 / 每小时推送 / stale fallback 已闭环
- `daytime-sync` 的 attention 新鲜度问题已经解决

2026-03-26 的再次复核里，真实 `openclaw cron list --all --json` 只看到一个 Twinbox 相关 job：`twinbox-daily-refresh`。它的 payload 是 Twinbox 主动维护的 `systemEvent -> daytime-sync` bridge job；`weekly-refresh` 和 `nightly-full-refresh` 没有随着 `SKILL.md` metadata 自动出现。所以当前仍不能把 metadata schedules 当成平台已自动接通的事实。

## 当前宿主桥接面

- Twinbox 侧现在已有两条宿主桥接入口：
  - `scripts/twinbox_openclaw_bridge.sh`
  - `scripts/twinbox_openclaw_bridge_poll.sh`
- 前者适合宿主已经拿到明确 `system-event` 文本时直接转发
- 后者适合宿主机 service 每分钟轮询一次 Gateway 的 `cron.list` / `cron.runs`，消费新的 Twinbox `systemEvent` run
- 本目录也补了最小用户态 systemd 样例：
  - [twinbox-openclaw-bridge.service](./twinbox-openclaw-bridge.service)
  - [twinbox-openclaw-bridge.timer](./twinbox-openclaw-bridge.timer)
  - [twinbox-openclaw-bridge.env.example](./twinbox-openclaw-bridge.env.example)
  - [../scripts/install_openclaw_bridge_user_units.sh](../scripts/install_openclaw_bridge_user_units.sh)
- 2026-03-25 已在本机完成一次真实 smoke：
  - 官方 `openclaw-gateway.service` 由 `openclaw gateway install --force` 安装
  - Twinbox bridge timer 已安装到 `~/.config/systemd/user/`
  - 临时 `systemEvent` cron run 能被 poller 消费并落盘为 `schedule-runs.jsonl` + `activity-pulse.json`

## 渐进式优化顺序

当前不建议一上来就把 Twinbox 做成“重插件 + 全自动 runtime”。

更稳的推进顺序是：

1. 先把根 `SKILL.md` 做成薄而准的 Markdown skill
   - 常见请求固定走 `twinbox task ...`
   - 把 `skills.entries.twinbox.env`、`skillsSnapshot`、专用 `twinbox` agent 写清楚
2. 再把 deployment / prompt smoke 做成固定回归面
   - 明确哪些是已证实行为，哪些只是声明层
3. 然后把宿主 bridge / poller / timer 打磨成可靠闭环
   - 再讨论 retry、告警、stale fallback
4. 最后才评估把少数高频任务升级成 plugin tool
   - 目标是降低“只读 skill 不执行命令”的概率
   - 不是把整个 Twinbox 一次性迁到 plugin SDK

## 为什么 smoke 先固定这几个 task 入口

当前把 prompt smoke 先固定在 `latest-mail`、`todo`、`progress`、`mailbox-status`，不是因为 Twinbox 的底层能力只有这四块，而是因为它们最适合作为 hosted skill 的第一批确定性入口。

判断标准是：

1. 通用：不绑定具体公司和岗位画像
2. 薄包装：都直接映射到现有 CLI / artifact，不新增推理链路
3. 只读：适合先做可靠性验证
4. 可验：最容易暴露“模型只是读了 skill，没有执行命令”
5. 覆盖核心问题：总览、待办、下钻、健康检查

按当前实现的底层映射：

- `latest-mail` -> `digest pulse` / `activity-pulse.json` / `daily-urgent` (含角色降权)
- `todo` -> `queue urgent` + `queue pending` + 现有 action/review 投影 (含视觉标注与降权)
- `progress` -> `thread progress`
- `mailbox-status` -> `mailbox preflight`

其中 `todo` 路由还会把 recipient routing 信号显式投影出来（支持全链路降权反馈）：

- `[CC]` = 邮箱 owner 在 `Cc` 列表或混合间接状态 (降权 0.6)
- `[GRP]` = 邮箱 owner 仅通过邮件组或别名收到 (降权 0.4)
- 2026-03-25 起，`group_only` 已支持独立识别且不再静默折叠成 `cc_only`；`daytime-sync` 任务也已扩展覆盖至 Phase 4，实现日内即时可见的降权反馈。

因此：

- 这几个入口属于 hosted 适配层，不是新的领域核心
- Twinbox 的底层 source of truth 仍然是 `mailbox` / `queue` / `thread` / `digest` / `action` / `review` / `orchestrate`
- `weekly` 保留为补充入口，但不是 smoke 第一优先级

## Source Of Truth

- OpenClaw 官方文档：`docs.openclaw.ai` 当前页面
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

- [DEPLOY.md](./DEPLOY.md)：Twinbox × OpenClaw **正式部署指南**（主路径、迁移、插件、清单、排障与回滚）
- [twinbox-openclaw-bridge.service](./twinbox-openclaw-bridge.service)：用户态宿主 poller service 样例
- [twinbox-openclaw-bridge.timer](./twinbox-openclaw-bridge.timer)：每分钟轮询一次 Gateway cron run 的 timer 样例
- [twinbox-openclaw-bridge.env.example](./twinbox-openclaw-bridge.env.example)：`%h/.config/twinbox/twinbox-openclaw-bridge.env` 样例
- [../scripts/install_openclaw_bridge_user_units.sh](../scripts/install_openclaw_bridge_user_units.sh)：安装到 `~/.config/systemd/user/` 的辅助脚本
- [../scripts/install_openclaw_twinbox_init.sh](../scripts/install_openclaw_twinbox_init.sh)：初始化 `code-root` / `state-root` / legacy `canonical-root` 的脚本
