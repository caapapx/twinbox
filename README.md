# twinbox

[English Version](#english-version)

一个 OpenClaw 原生、以线程为中心的邮件 Copilot。它会基于邮箱证据、人类上下文与受控自动化，逐步学习用户的真实工作流。

## 这个仓库是什么

`twinbox` 不是一个通用的自动发信机器人，也不是一个打磨好的收件箱客户端演示。

它是一个可自托管的基础设施，用于构建邮件 Copilot，具备以下特征：

- 从只读邮箱接入开始
- 基于线程而不是单封邮件重建工作流状态
- 摄取用户提供的上下文（如工作资料、重复性习惯）
- 将邮箱状态转成可见队列（如 `daily-urgent`、`pending-replies`）
- 动作能力按阶段升级：`read-only -> draft -> controlled send`

当前仓库已包含：

- 基于 shell 的邮箱校验与采样脚本
- 适用于 OpenClaw 或手工初始化的稳定渐进式验证模板
- 面向用户资料与习惯的上下文摄取模型
- 一套新的 spec-first 运行时骨架（listener、action、template、audit logging）

## 为什么做这个项目

多数邮件 Agent 演示更关注消息事件、快速自动化和 UI 交互。

这个项目针对的是另一类问题：

- 企业级安全上线
- 线程中心的工作流理解
- 人在回路中的决策机制
- OpenClaw 原生自托管与调度
- 从单个真实邮箱逐步迁移为可复用的 Agent 工作流

理想效果不是“AI 读了一封邮件”，而是“AI 能成为符合这个人真实工作方式的可用邮件 Copilot”。

## 当前状态

当前发布姿态：`spec-first`、`shell-first`、`read-only-first`。

仓库里已实现：

- IMAP/SMTP 环境检查与本地 `himalaya` 配置渲染
- 只读邮箱冒烟测试与早期验证脚本
- 关于 persona、生命周期和日常价值输出的渐进式验证文档
- 线程中心工作流与人类上下文摄取的架构文档
- 面向后续 `listener`、`action`、`template`、`audit` 层的运行时骨架

明确暂未实现：

- 常驻 listener 管理器
- 生产级 action 管理器
- WebSocket / 前端交互层
- 默认自动发送或归档自动化
- 租户特定的硬编码业务逻辑

## 核心设计决策

1. `Thread over message`  
   决策基于线程上下文、工作流阶段和证据，而不是孤立的单邮件快照。
2. `Value before automation`  
   系统必须先证明只读阶段有价值，再进入草稿；草稿阶段证明价值后才进入发送。
3. `Context is first-class`  
   用户上传资料、重复习惯和确认事实会被结构化沉淀，而不是埋在聊天历史里。
4. `OpenClaw-native operation`  
   该仓库既面向 OpenClaw 风格的自托管环境，也支持手工聊天驱动的初始化。

## 架构图（ASCII）

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

## 与 Anthropic `email-agent` 架构图对比

Anthropic 原项目 README 架构图（已手动同步到本仓库）：

![Anthropic Email Agent Architecture](docs/assets/anthropic-email-agent-architecture.png)

核心差异（本仓库 vs Anthropic demo）：

- `线程优先` vs `消息/交互优先`：本仓库以 thread state 作为主轴，强调状态重建与队列投影。
- `渐进式自动化` vs `直接功能演示`：本仓库默认 `read-only -> draft -> controlled send`，先验证价值再放权。
- `上下文平面` vs `即时会话`：本仓库把用户资料/习惯结构化沉淀，不依赖一次性对话上下文。
- `自托管工作流稳定化` vs `本地 demo`：本仓库面向可演进的运行时骨架（listener/action/template/audit）。

## 仓库结构

```text
twinbox/
├── README.md
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

## 从这里开始

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

## 运行时方向

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

## 默认安全策略

- 只使用 app/client 密码。
- `.env` 仅保存在本地，禁止提交。
- `runtime/` 视为本地运行数据。
- 在草稿质量与审批流验证完成前，不开启自动发送。
- 不允许用户提供的上下文静默覆盖邮箱事实。

## 发布前的重要说明

仓库 `docs/validation/` 下仍包含来自真实邮箱研究的本地生成验证材料。正式完全公开前，应审查并脱敏所有实例相关文件和历史记录。

面向开源用户的架构与模板文档位于 `docs/validation/` 之外，应保持为稳定的公共接口。

## English Version

An OpenClaw-native, thread-centric email copilot that progressively learns a user's workflow from mailbox evidence, human context, and controlled automation.

### What This Repository Is

`twinbox` is not a generic auto-send mail bot and not a polished inbox client demo.

It is a self-hostable foundation for building an email copilot that:

- starts with read-only mailbox onboarding
- reconstructs workflow state from threads instead of single messages
- ingests user-supplied context such as work materials and recurring habits
- turns mailbox state into visible queues like `daily-urgent` and `pending-replies`
- only promotes actions gradually: read-only -> draft -> controlled send

This repository currently combines:

- shell-based mailbox validation and sampling scripts
- a stable progressive validation template for OpenClaw or manual initialization
- a context-ingestion model for user-provided materials and habits
- a new spec-first runtime skeleton for listeners, actions, templates, and audit logging

### Why This Project Exists

Most email-agent demos optimize for message events, fast automation, and UI interaction.

This project optimizes for a different problem:

- enterprise-safe rollout
- thread-centric workflow understanding
- human-in-the-loop decision making
- OpenClaw-native self-hosting and scheduling
- gradual adaptation from one real mailbox into a reusable agent workflow

The result should feel less like "AI reads one email" and more like "AI becomes a usable mailbox copilot for how this person actually works".

### Current Status

Current release posture: `spec-first`, `shell-first`, `read-only-first`.

What is already in the repository:

- IMAP/SMTP environment checks and local `himalaya` config rendering
- read-only mailbox smoke test and early validation scripts
- progressive validation docs for persona, lifecycle, and daily value outputs
- architecture docs for thread-centric workflow and human context ingestion
- runtime skeleton for future `listener`, `action`, `template`, and `audit` layers

What is intentionally not implemented yet:

- a long-running listener manager
- a production action manager
- WebSocket/frontend interaction surfaces
- auto-send or archive automation by default
- tenant-specific hardcoded business logic

### Core Design Decisions

1. `Thread over message`  
   Decisions are made on thread context, workflow stage, and evidence, not on isolated message snapshots.
2. `Value before automation`  
   The system must prove read-only value before drafting, and prove draft value before sending.
3. `Context is first-class`  
   User-uploaded materials, recurring habits, and confirmed facts are normalized instead of buried in chat history.
4. `OpenClaw-native operation`  
   The repo is designed to work in OpenClaw-style self-hosted environments and also in manual chat-driven initialization.

### Architecture Diagram (ASCII)

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
                                 | Runtime Skeleton   |------------------------+
                                 | listener / action  |     typed context
                                 | template / audit   |
                                 +---------+----------+
                                           |
                                           v
                                 +---------+----------+
                                 | Automation Gates   |
                                 | read -> draft ->   |
                                 | controlled send    |
                                 +--------------------+
```

### Comparison with Anthropic `email-agent` Diagram

Anthropic README architecture diagram (mirrored into this repo):

![Anthropic Email Agent Architecture](docs/assets/anthropic-email-agent-architecture.png)

Key differences (this repo vs Anthropic demo):

- `Thread-first` vs `message/UI-event-first`: this repo models thread lifecycle and queue projection as core state.
- `Progressive automation` vs `direct demo flow`: this repo enforces `read-only -> draft -> controlled send`.
- `Context as structured plane` vs `ad-hoc session context`: user materials/habits are normalized for reuse.
- `Self-hostable runtime skeleton` vs `local demo app`: this repo emphasizes listener/action/template/audit evolution.

### Repository Map

```text
twinbox/
├── README.md
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

### Start Here

1. Read [architecture.md](docs/architecture.md).
2. Read [openclaw-progressive-validation-plan.md](docs/openclaw-progressive-validation-plan.md).
3. Read [open-source-v1-plan.md](docs/release/open-source-v1-plan.md).
4. If you want to validate mailbox access locally, run:
   - `bash scripts/check_env.sh`
   - `bash scripts/render_himalaya_config.sh`
   - `bash scripts/preflight_mailbox_smoke.sh --headless`
5. If you want to extend the runtime skeleton, start from:
   - [agent/README.md](agent/README.md)
   - [thread-state-runtime.md](docs/specs/thread-state-runtime.md)
   - [types.ts](agent/custom_scripts/types.ts)

### Runtime Direction

The next runtime layer will not clone Anthropic's `email-agent` directly.

It will keep this repository's strengths:

- progressive validation
- thread-centric workflow state
- human context plane
- controlled automation gates

And absorb the engineering pieces that matter:

- `listener` / `action` separation
- `template` / `instance` separation
- typed execution context
- execution audit trail
- enable/disable friendly extension surface

### Safety Defaults

- Use app/client passwords only.
- Keep `.env` local and never commit it.
- Treat `runtime/` as local operational data.
- Do not auto-send until draft quality and approval flow are proven.
- Do not let user-supplied context silently overwrite mailbox facts.

### Important Publishing Note

This repository still contains locally generated validation materials under `docs/validation/` from a real mailbox study. Before a fully public release, you should review and sanitize any instance-specific files and history.

The open-source-facing architecture and template docs live outside `docs/validation/` and should remain the stable public surface.
