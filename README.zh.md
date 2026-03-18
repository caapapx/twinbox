# twinbox 📮

[English](./README.md) | [中文](./README.zh-CN.md)

`twinbox` 是一个基于 OpenClaw 的、以 Thread 为中心的邮件 Copilot：先理解 Thread 状态，再逐步解锁自动化。

## 它是什么

`twinbox` 不是一个通用的自动发邮件机器人，也不是一个完善的收件箱客户端演示。

它是一个可自托管的基础框架，用于构建具有以下特性的邮件 Copilot：

- 从只读邮箱引导开始
- 从 Thread 中重建工作流状态，而不是简单的单一消息
- 摄取用户提供的 Context，如工作材料和习惯
- 将邮箱状态转化为可见队列，如 `daily-urgent` 和 `pending-replies`
- 仅逐步提升操作权限：只读 -> 草稿 -> 受控发送

目前已实现：

- 基于 shell 的邮箱验证和采样脚本
- 适用于 OpenClaw 或手动初始化的稳定渐进式验证模板
- 用于用户提供材料和习惯的 Context Ingestion 模型
- 用于 Listener、Action、Template 和 Audit Logging 的新 Spec-first Runtime Skeleton

## 为什么存在这个仓库

大多数邮件 Agent 演示往往优化消息事件、快速自动化和 UI 交互。

本项目针对一套不同的目标进行了调整：

- 企业安全部署
- 以 Thread 为中心的工作流理解
- 人机协作决策
- OpenClaw 原生自托管和调度
- 从一个真实邮箱逐步适配为可重用的 Agent 工作流

结果应该感觉不像是"AI 读取一封邮件"，而更像是"AI 成为一个人真实工作方式的可用邮箱 Copilot"。

## 当前进度

当前发布基调：`spec-first`, `shell-first`, `read-only-first`。

仓库现有内容：

- IMAP/SMTP 环境检查和本地 `himalaya` 配置渲染
- 只读邮箱冒烟测试和早期验证脚本
- 关于 Persona、Lifecycle 和日常价值输出的渐进式验证文档
- 关于以 Thread 为中心的工作流和人工 Context Ingestion 的架构文档
- 未来 `Listener`、`Action`、`Template` 和 `Audit` 层的 Runtime Skeleton

尚未实现：

- 长时间运行的 Listener Manager
- 生产环境 Action Manager
- WebSocket/前端交互界面
- 默认自动发送或归档自动化
- 特定于租户的硬编码业务逻辑

## 关键权衡

1. `Thread over Message`
   决策基于 Thread Context、工作流阶段和证据，而不是孤立的消息快照。
2. `Value before Automation`
   系统必须在起草之前证明只读价值，并在发送之前证明草稿价值。
3. `Context is First-class`
   用户上传的材料、反复出现的习惯和已确认的事实会被规范化，不会埋没在聊天记录中。
4. `OpenClaw-native Operation`
   仓库设计为在 OpenClaw 风格的自托管环境中运行，也支持手动聊天驱动的初始化。

## 架构图 (ASCII) 🧭

```text
                                +----------------------+
                                |   用户 / Operator     |
                                |  (审查并批准)         |
                                +----------+-----------+
                                           |
                                           v
+------------------+             +---------+----------+             +----------------------+
| 邮箱 (IMAP)       +-----------> | Thread State Layer | <---------- | Context Ingestion    |
| 首先只读          | 证据         | (Thread Lifecycle, |   事实      | (Materials/Habits)   |
+------------------+             | Queue Projection)  |             +----------+-----------+
                                 +---------+----------+                        |
                                           |                                   |
                                           v                                   |
                                 +---------+----------+                        |
                                 | Runtime Skeleton   |------------------------+
                                 | Listener / Action  |     Typed Context
                                 | Template / Audit   |
                                 +---------+----------+
                                           |
                                           v
                                 +---------+----------+
                                 | Automation Gates   |
                                 | 只读 -> 草稿 ->    |
                                 | 受控发送           |
                                 +--------------------+
```

## 比较：Anthropic `email-agent` 架构图

Anthropic 项目 README 架构图：

![Anthropic Email Agent Architecture](docs/assets/anthropic-email-agent-architecture.png)

此仓库与 Anthropic 演示的主要区别：

- `Thread-first` vs `Message/UI-event-first`：本仓库将 Thread Lifecycle 和 Queue Projection 作为核心状态建模。
- `Progressive Automation` vs `Direct Demo Flow`：本仓库强制执行 `只读 -> 草稿 -> 受控发送`。
- `Context as Structured Plane` vs `Ad-hoc Session Context`：用户 Materials/Habits 被规范化以供重用。
- `Self-hostable Runtime Skeleton` vs `Local Demo App`：本仓库强调 Listener/Action/Template/Audit 层的演进。

## 仓库地图

```text
twinbox/
├── README.md
├── README.zh.md
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
4. 如果你想在本地验证邮箱访问权限，运行：
   - `bash scripts/check_env.sh`
   - `bash scripts/render_himalaya_config.sh`
   - `bash scripts/preflight_mailbox_smoke.sh --headless`
5. 如果你想扩展 Runtime Skeleton，从以下文件开始：
   - [agent/README.md](agent/README.md)
   - [thread-state-runtime.md](docs/specs/thread-state-runtime.md)
   - [types.ts](agent/custom_scripts/types.ts)

## 运行时未来方向

下一个 Runtime 层不会直接克隆 Anthropic 的 `email-agent`。

它将保持本仓库的优势：

- 渐进式验证
- 以 Thread 为中心的工作流状态
- 人工 Context Plane
- 受控 Automation Gates

并将吸收重要的工程组件：

- `Listener` / `Action` 分离
- `Template` / `Instance` 分离
- Typed Execution Context
- Execution Audit Trail
- 易于扩展的 Enable/Disable 接口

## 安全边界

- 仅使用应用/客户端专用密码。
- 保持 `.env` 本地化，绝对不要提交它。
- 将 `runtime/` 视为本地运行数据。
- 在证明草稿质量和审批流程有效之前，不要自动发送。
- 不要让用户提供的 Context 静默覆盖邮箱事实。

## 发布说明

该仓库的 `docs/validation/` 下仍包含从真实邮箱研究中生成的本地验证材料。在完全开放之前，你应该审查并清理任何特定于实例的文件和历史记录。

面向开源的架构和模板文档位于 `docs/validation/` 之外，应保持为稳定的公共接口。
