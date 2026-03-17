# Twinbox 📮

[English](README.md)

一个 OpenClaw 原生、以线程为中心的邮件 Copilot：先帮你看懂线程状态，再逐步放开自动化能力。

## 这是个什么项目

`twinbox` 不是一个通用的自动发信机器人，也不是一个打磨好的收件箱客户端演示。

它是一个可自托管的基础设施，用来构建邮件 Copilot，特点是：

- 从只读邮箱接入开始
- 基于线程而不是单封邮件重建工作流状态
- 摄取用户提供的上下文（如工作资料、重复性习惯）
- 将邮箱状态转成可见队列（如 `daily-urgent`、`pending-replies`）
- 动作能力按阶段升级：`read-only -> draft -> controlled send`

现在已经有：

- 基于 shell 的邮箱校验与采样脚本
- 适用于 OpenClaw 或手工初始化的稳定渐进式验证模板
- 面向用户资料与习惯的上下文摄取模型
- 一套新的 spec-first 运行时骨架（listener、action、template、audit logging）

## 为什么要做它

多数邮件 Agent 演示更关注消息事件、快速自动化和 UI 交互。

这个项目更关心另一类问题：

- 企业级安全上线
- 线程中心的工作流理解
- 人在回路中的决策机制
- OpenClaw 原生自托管与调度
- 从单个真实邮箱逐步迁移为可复用的 Agent 工作流

理想效果不是“AI 读了一封邮件”，而是“AI 能成为符合这个人真实工作方式的可用邮件 Copilot”。

## 进度一览

当前发布姿态：`spec-first`、`shell-first`、`read-only-first`。

仓库里已实现：

- IMAP/SMTP 环境检查与本地 `himalaya` 配置渲染
- 只读邮箱冒烟测试与早期验证脚本
- 关于 persona、生命周期和日常价值输出的渐进式验证文档
- 线程中心工作流与人类上下文摄取的架构文档
- 面向后续 `listener`、`action`、`template`、`audit` 层的运行时骨架

还没做的部分：

- 常驻 listener 管理器
- 生产级 action 管理器
- WebSocket / 前端交互层
- 默认自动发送或归档自动化
- 租户特定的硬编码业务逻辑

## 几个关键取舍

1. `Thread over message`  
   决策基于线程上下文、工作流阶段和证据，而不是孤立的单邮件快照。
2. `Value before automation`  
   系统必须先证明只读阶段有价值，再进入草稿；草稿阶段证明价值后才进入发送。
3. `Context is first-class`  
   用户上传资料、重复习惯和确认事实会被结构化沉淀，而不是埋在聊天历史里。
4. `OpenClaw-native operation`  
   该仓库既面向 OpenClaw 风格的自托管环境，也支持手工聊天驱动的初始化。

## 架构图（ASCII）🧭

```text
                                +----------------------+
                                |   User / Operator    |
                                |  (review & approve)  |
                                +----------+-----------+
                                           |
                                           v
+------------------+             +---------+----------+             +----------------------+
| Mailbox (IMAP)   +-----------> | Thread State Layer | <---------- | Context Ingestion     |
| read-only first  | evidence    | (thread lifecycle, |   facts     | (materials/habits)    |
+------------------+             | queue projection)  |             +----------+-----------+
                                 +---------+----------+                        |
                                           |                                   |
                                           v                                   |
                                 +---------+----------+                        |
                                 | Runtime Skeleton   |                        |
                                 | listener / action  |------------------------+
                                 | template / audit   |     typed context
                                 +---------+----------+
                                           |
                                           v
                                 +---------+----------+
                                 | Automation Gates   |
                                 | read -> draft ->   |
                                 | controlled send    |
                                 +--------------------+
```

## 对比：Anthropic `email-agent` 架构图

Anthropic 项目 README 架构图：

![Anthropic Email Agent Architecture](docs/assets/anthropic-email-agent-architecture.png)

主要差异（本仓库 vs Anthropic demo）：

- `线程优先` vs `消息/交互优先`：本仓库以 thread state 作为主轴，强调状态重建与队列投影。
- `渐进式自动化` vs `直接功能演示`：本仓库默认 `read-only -> draft -> controlled send`，先验证价值再放权。
- `上下文平面` vs `即时会话`：本仓库把用户资料/习惯结构化沉淀，不依赖一次性对话上下文。
- `自托管工作流稳定化` vs `本地 demo`：本仓库面向可演进的运行时骨架（listener/action/template/audit）。

## 仓库结构

```text
twinbox/
├── README.md
├── README.en.md
├── SKILL.md
├── agent/
│   ├── README.md
│   └── custom_scripts/
│       ├── types.ts
│       ├── listeners/
│       └── actions/
├── config/
│   ├── action-templates/
│   ├── context/
│   └── profiles/
├── docs/
│   ├── architecture.md
│   ├── openclaw-progressive-validation-plan.md
│   ├── release/open-source-v1-plan.md
│   └── specs/thread-state-runtime.md
├── scripts/
└── runtime/
```

## 快速开始 🚀

1. 阅读 [architecture.md](docs/architecture.md)。
2. 阅读 [openclaw-progressive-validation-plan.md](docs/openclaw-progressive-validation-plan.md)。
3. 阅读 [open-source-v1-plan.md](docs/release/open-source-v1-plan.md)。
4. 如果你要在本地验证邮箱访问，运行：
   - `bash scripts/check_env.sh`
   - `bash scripts/render_himalaya_config.sh`
   - `bash scripts/preflight_mailbox_smoke.sh --headless`
5. 如果你要扩展运行时骨架，建议从以下文件开始：
   - [agent/README.md](agent/README.md)
   - [thread-state-runtime.md](docs/specs/thread-state-runtime.md)
   - [types.ts](agent/custom_scripts/types.ts)

## 接下来会怎么演进

下一层运行时不会直接照搬 Anthropic 的 `email-agent`。

它会保留本仓库的优势：

- 渐进式验证
- 线程中心工作流状态
- 人类上下文平面
- 受控自动化闸门

并吸收关键工程能力：

- `listener` / `action` 分离
- `template` / `instance` 分离
- 类型化执行上下文
- 执行审计轨迹
- 易于启用/停用的扩展界面

## 默认安全边界

- 只使用 app/client 密码。
- `.env` 仅保存在本地，禁止提交。
- `runtime/` 视为本地运行数据。
- 在草稿质量与审批流验证完成前，不开启自动发送。
- 不允许用户提供的上下文静默覆盖邮箱事实。

## 发布前提醒

仓库 `docs/validation/` 下仍包含来自真实邮箱研究的本地生成验证材料。正式完全公开前，应审查并脱敏所有实例相关文件和历史记录。

面向开源用户的架构与模板文档位于 `docs/validation/` 之外，应保持为稳定的公共接口。
