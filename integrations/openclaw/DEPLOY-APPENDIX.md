# Twinbox × OpenClaw 部署附录

> 操作主路径见 [DEPLOY.md](./DEPLOY.md)；排障见 [TROUBLESHOOT.md](./TROUBLESHOOT.md)。

---

## 附录 A：OpenClaw 官方文档与 twinbox 映射

权威顺序：**官方当前文档 > 本目录 [README.md](./README.md) 与实测 > 社区镜像**。

### A.1 官方文档索引与精读清单

| 主题 | URL | 与 twinbox 的关系 |
|------|-----|-------------------|
| 全站索引（机器可读） | [llms.txt](https://docs.openclaw.ai/llms.txt) | 快速定位 skill / gateway / plugin / automation |
| 编写 Skill | [Creating Skills](https://docs.openclaw.ai/tools/creating-skills) | `name` / `description`、`openclaw agent` 冒烟 |
| 加载与优先级 | [Skills](https://docs.openclaw.ai/tools/skills) | `/skills` → `~/.openclaw/skills`；`metadata` 单行 JSON；session 快照 |
| 配置模式 | [Skills Config](https://docs.openclaw.ai/tools/skills-config) | `skills.entries.twinbox.env`；sandbox 不继承宿主 env |
| CLI | [skills](https://docs.openclaw.ai/cli/skills.md) / [cron](https://docs.openclaw.ai/cli/cron.md) / [gateway](https://docs.openclaw.ai/cli/gateway.md) | 安装、定时、Gateway 运维 |
| HTTP 调工具 | [Tools Invoke API](https://docs.openclaw.ai/gateway/tools-invoke-http-api) | Bearer `POST /tools/invoke`；默认拒绝列表含 `cron` |
| 定时 | [Cron Jobs](https://docs.openclaw.ai/automation/cron-jobs) | `~/.openclaw/cron/`；`system-event` 等 |
| Cron vs Heartbeat | [Cron vs Heartbeat](https://docs.openclaw.ai/automation/cron-vs-heartbeat) | 精确时刻 vs 批量巡检 |
| 频道 Poll | [Polls](https://docs.openclaw.ai/automation/poll) | IM 投票，非宿主机轮询 |
| Hooks | [Hooks](https://docs.openclaw.ai/automation/hooks.md) | 事件扩展；twinbox 当前以 cron + bridge 为主 |
| 沙箱与策略 | [Sandboxing](https://docs.openclaw.ai/gateway/sandboxing.md) 等 | 与 Phase 1–4 只读一致评估 |
| 插件 | [Building Plugins](https://docs.openclaw.ai/plugins/building-plugins.md) 等 | 见 [DEPLOY.md §3.5](./DEPLOY.md) |

### A.2 OpenClaw 能力 ↔ twinbox 模块

| OpenClaw 能力 | twinbox 侧落点 |
|---------------|----------------|
| `skills.entries.<name>.env` | 邮箱与宿主 env |
| `metadata.openclaw.requires.env` / `login.preflightCommand` | [SKILL.md](../SKILL.md)、[docs/ref/cli.md](../docs/ref/cli.md) |
| `config/schedules.yaml` + Twinbox bridge cron sync | 当前默认 schedule 来源；[docs/ref/scheduling.md](../docs/ref/scheduling.md) |
| Gateway `cron` + `system-event` | [scripts/twinbox_openclaw_bridge.sh](../scripts/twinbox_openclaw_bridge.sh)、poller、[openclaw_bridge.py](../src/twinbox_core/openclaw_bridge.py) |
| `openclaw skills list` / `info` | 部署验证；≠ 当前 session 已注入 |
| 插件 `registerTool()` | 缓解「只读 SKILL」 |

### A.3 Markdown skill 与插件对比

| 方式 | 适用 | twinbox 现状 |
|------|------|--------------|
| Markdown `SKILL.md` + exec | 迭代快 | **默认** |
| 插件 `registerTool` | 稳定 schema、确定性任务 | **按需** |

### A.4 ClawHub / 社区样例（结构参考）

第三方 skill 视为不可信代码，仅借鉴文档结构：如 [Ai Provider Bridge](https://clawhub.com/skills/ai-provider-bridge)、[summarize](https://clawhub.ai/skills/summarize)、[agent-zero-bridge](https://playbooks.com/skills/openclaw/skills/agent-zero-bridge)。

---

## 附录 B：验证检查清单

以下勾选以仓库内 native + Twinbox smoke 为参考；未勾选表示待验证或待补证据。

### B.1 部署前（宿主 / Twinbox）

- [x] `twinbox mailbox preflight --json` 本地成功
- [x] `twinbox-orchestrate run --phase 4` 本地成功
- [x] 根 [SKILL.md](../SKILL.md) 元数据与实现一致
- [x] schedule 相关命令使用 `twinbox-orchestrate`
- [x] OpenClaw 侧能拿到 Twinbox 所需 env（含 `skills.entries.twinbox.env`）
- [x] `~/.config/twinbox/code-root` / `state-root` 已初始化
- [x] `~/.openclaw/openclaw.json` 模型与 secret 已就绪

### B.2 托管接入

- [x] `openclaw agent --agent twinbox … --json` 中 `systemPromptReport.skills.entries` 含 `twinbox`（2026-03-26 本机复验）
- [x] OpenClaw 能读取 skill manifest
- [x] `openclaw skills info twinbox` 展示 `requires.env`
- [ ] 平台是否自动收集 / 透传 env
- [ ] OpenClaw 是否调用 `preflightCommand`；失败时是否呈现 `missing_env` / `actionable_hint`
- [x] preflight 成功后宿主可进入 phase 验证
- [x] `openclaw skills info twinbox` 显示 `Ready`
- [x] 根 SKILL 已提供 `twinbox task ...` 入口
- [x] 显式探针可触发 `twinbox task`（不等于自然话术已稳定）

**验证记录（摘录）**：2026-03-25 起，本机曾用 `openclaw agent --agent twinbox` 对 `latest-mail`、`todo`、`progress` 等做探针；曾暴露 `mailbox-status` 参数问题（已修复为 `account_override`）。自然话术与空 `assistant.content`、isolated cron session 行为等仍属平台与路由层待观察项，**不应**将单次探针等同于产品级 SLA。

### B.3 调度与桥接

- [x] Gateway 健康检查与 `system-event` smoke
- [x] `cron` 创建 / debug `systemEvent` job
- [x] 宿主机 poller：`scripts/twinbox_openclaw_bridge_poll.sh`
- [x] 用户态 timer 样例安装与 `daytime-sync` 触发（以你环境日志为准）
- [ ] skill schedule metadata 是否被平台解析
- [ ] 失败重试 / 告警 / stale 恢复责任
- [x] 已确认 `daytime-sync` 与 Phase 4 overlay 等行为边界（见调度文档）

### B.4 上线后

- [x] 至少一次日内 schedule smoke
- [ ] weekly refresh 至少成功一次
- [x] phase4 产物可被 queue / digest 消费
- [x] 至少一次 chat-visible 定时推送类 smoke（独立 cron session）
- [ ] preflight 错误对终端用户可见
- [ ] stale 队列识别与恢复
- [x] 无自动发送 / 破坏性邮箱操作

---

**文档版本**：本文为附录；操作主路径见 [DEPLOY.md](./DEPLOY.md)，设计模型见 [docs/ref/openclaw-deploy-model.md](../docs/ref/openclaw-deploy-model.md)，排障见 [TROUBLESHOOT.md](./TROUBLESHOOT.md)。
