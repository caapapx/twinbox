# twinbox 📮

[English](./README.md) | [中文](./README.zh.md)

`twinbox` 是一个以线程为中心的邮件 Copilot 基础设施：从线程重建工作流状态，而非处理单条消息；先理解状态，再逐步解锁自动化。

截至 `2026-03-23` 的实际状态：仓库处于实现收敛阶段，以只读能力优先。当前已经具备 Phase 1-4 的共享 Python Core、稳定的编排契约 CLI，以及 Phase 4 的准确率/回归门禁入口（`twinbox-eval-phase4`）；还不是包含 listener/action 常驻服务的完整生产运行时。

## 它是什么

`twinbox` 不是一个通用的自动发邮件机器人，也不是一个完善的收件箱客户端演示。

它是一个可自托管的基础框架，用于构建具有以下特性的邮件 Copilot：

- 从只读邮箱引导开始
- 从 Thread 中重建 workflow state，而不是简单的单一 message
- ingest 用户提供的 context（如工作材料和习惯）
- 将邮箱 state 投影为可见 queue（如 `daily-urgent` 和 `pending-replies`）
- 仅逐步提升操作权限：只读 -> 草稿 -> 受控发送

目前已实现：

- 基于 shell 的邮箱验证和采样脚本
- Phase 1-4 loading/thinking 与渲染的共享 Python Core
- 共享编排契约入口（`scripts/twinbox_orchestrate.sh`）
- Phase 4 准确率/回归评测入口（`twinbox-eval-phase4`）
- 用于用户材料、习惯、确认事实的 Context Ingestion 能力

## 为什么存在这个仓库

大多数邮件 Agent 演示往往优化消息事件、快速自动化和 UI 交互。

本项目针对一套不同的目标进行了调整：

- 企业安全部署
- 以 Thread 为中心的 workflow 理解
- human-in-the-loop 决策
- OpenClaw 原生自托管和调度
- 从一个真实邮箱逐步适配为可重用的 Agent 工作流

结果应该感觉不像是 "AI 读取一封邮件"，而更像是 "AI 融入真实工作方式的 mailbox Copilot"。

## 当前进度

当前发布基调：`spec-first`, `shell-first`, `read-only-first`。

仓库现有内容：

- IMAP/SMTP 环境检查和本地 `himalaya` 配置渲染
- 只读邮箱冒烟测试和早期验证脚本
- 关于 Persona、Lifecycle 和日常价值输出的渐进式验证文档
- 关于以 Thread 为中心的工作流和人工 Context Ingestion 的架构文档
- 未来 `Listener`、`Action`、`Template` 和 `Audit` 层的 Runtime Skeleton
- Phase 1-4 的 Loading/Thinking 分离（LLM 替代硬编码推断）
- Phase 4 baseline 回退门禁评测

### 渐进式验证流水线

当前仓库实现的是一个 `4` 阶段、`read-only-first` 的 analysis funnel。
每个阶段都会收窄 attention window，并把结构化 artifact 交给下一阶段继续处理。

```mermaid
flowchart LR
    M["Mailbox<br/>envelopes + sampled bodies"]
    C["Human context<br/>materials / habits / confirmed facts"]
    P1["Phase 1<br/>Mailbox census + intent classification"]
    B1["attention-budget v1<br/>noise filtered"]
    P2["Phase 2<br/>Persona + business hypotheses"]
    B2["attention-budget v2<br/>role-relevant threads"]
    P3["Phase 3<br/>Lifecycle modeling"]
    B3["attention-budget v3<br/>modeled threads"]
    P4["Phase 4<br/>Daily value outputs"]
    O["Outputs<br/>daily-urgent / pending-replies / sla-risks / weekly-brief"]

    M --> P1 --> B1 --> P2 --> B2 --> P3 --> B3 --> P4 --> O
    C --> P2
    C --> P3
    C --> P4
```

| Phase | 核心工作 | 典型产物 | 这一阶段的意义 |
|-------|----------|----------|----------------|
| 1 | 在分布层面读懂邮箱 | `phase1-context.json`、`intent-classification.json`、派生 census views | 先建立全局 baseline，并尽早过滤明显噪声 |
| 2 | 推断这个邮箱对应的人和业务 | `persona-hypotheses.yaml`、`business-hypotheses.yaml` | 用 role、business 和 context relevance 继续缩小范围 |
| 3 | 从标签升级到 thread 级 lifecycle state | `lifecycle-model.yaml`、`thread-stage-samples.json` | 理解每条 thread 在重复 workflow 中的当前位置 |
| 4 | 产出用户真正会看的 value surfaces | `daily-urgent.yaml`、`pending-replies.yaml`、`sla-risks.yaml`、`weekly-brief.md` | 直接回答“今天我该看什么” |

当前 contract 说明：

- 当前实现里的 runtime handoff 仍主要依赖各 phase 的结构化 state files，而不是一条已经打通的 `attention-budget.yaml`
- `attention-budget` 目前应视为目标收敛 contract，而不是已经被脚本强制执行的 runtime dependency
- 详见 [Validation Artifact Contract](docs/ref/validation.md)

每个阶段内部仍保持同一套结构：

- `Loading`: 确定性 I/O、采样和 context-pack 构建
- `Thinking`: 带 evidence 与 confidence 的 LLM inference

```bash
# 单 Phase 执行
bash scripts/phase1_loading.sh && bash scripts/phase1_thinking.sh

# 共享编排 CLI
bash scripts/twinbox_orchestrate.sh run

# 查看可被 skill / adapter 消费的 contract
bash scripts/twinbox_orchestrate.sh contract --format json

# 通过编排 CLI 单跑某个 Phase
bash scripts/twinbox_orchestrate.sh run --phase 2

# 向后兼容 wrapper
bash scripts/run_pipeline.sh --phase 2
```

### 几种常用运行/测试方式

如果你只是想先选一条能直接执行的路径，按下面这张表挑就够了。

| 目标 | 推荐命令 | 说明 |
|------|----------|------|
| 先验证邮箱登录/连通性 | `twinbox mailbox preflight --json` | 统一执行 env 检查、默认值补全、himalaya 配置渲染和只读 IMAP 预检，适合 OpenClaw 消费 |
| 兼容旧脚本方式做 preflight | `bash scripts/preflight_mailbox_smoke.sh --json` | `twinbox mailbox preflight` 的兼容 wrapper，适合本地脚本迁移期 |
| 看整条 pipeline 会跑什么 | `bash scripts/twinbox_orchestrate.sh run --dry-run` | 不执行真实 phase，只打印 Phase 1-4 的执行顺序 |
| 本地跑完整流程 | `bash scripts/twinbox_orchestrate.sh run` | 共享编排 CLI，默认 Phase 4 走并行 thinking |
| 本地只跑单个 Phase | `bash scripts/twinbox_orchestrate.sh run --phase 2` | 适合局部调试、单阶段重跑 |
| 查看编排 contract | `bash scripts/twinbox_orchestrate.sh contract --format json` | 适合 operator、skill 或脚本读取 phase 依赖与入口 |
| 跑 Python 单测 | `pytest tests/` | 覆盖 contract、paths、LLM、renderer 和 phase core |
| 跑轻量 smoke | `python3 -m compileall src` 和 `bash -n scripts/twinbox_orchestrate.sh scripts/run_pipeline.sh` | 适合提交前做快速语法检查 |

### 共享状态根目录

Phase 1-4 显式区分 `code root` 和 `state root`，确保所有脚本写入同一 canonical 位置。

- `code root`：当前 checkout，提供受版本控制的脚本
- `state root`：canonical checkout，提供 `.env`、`runtime/context/`、`runtime/validation/` 和 `docs/validation/`
- 解析顺序：`TWINBOX_CANONICAL_ROOT` -> `~/.config/twinbox/canonical-root` -> 当前 checkout

```bash
# 在主 checkout 中执行一次，注册 canonical state root
bash scripts/register_canonical_root.sh
```

### 流水线 Checklist

1. 在主 checkout 里执行 `bash scripts/register_canonical_root.sh` 注册 canonical root。
2. 任意 Phase 都继续走原有脚本入口，Phase 1-4 都会解析同一份 canonical state root。
3. 当 skill 或 operator 需要显式读取 pipeline contract 时，用 `bash scripts/twinbox_orchestrate.sh contract --format json`。

```bash
# 查看共享 orchestration contract，或直接跑本地 CLI
bash scripts/twinbox_orchestrate.sh contract
bash scripts/twinbox_orchestrate.sh run

# 直接跑兼容 wrapper
bash scripts/run_pipeline.sh
```

详见统一文档入口 [docs/README.md](docs/README.md) 和 [核心重构计划](docs/core-refactor.md)。

尚未实现：

- 长时间运行的 Listener Manager
- 生产环境 Action Manager
- WebSocket/前端交互界面
- 默认自动发送或归档自动化
- 特定于租户的硬编码业务逻辑

## 关键权衡

1. `Thread over Message`
   决策基于 Thread context、workflow stage 和 evidence，而不是孤立的 message snapshot。
2. `Value before Automation`
   系统必须在 drafting 之前证明 read-only value，并在 sending 之前证明 draft value。
3. `Context is First-class`
   用户上传的 materials、反复出现的 habits 和已确认 facts 会被规范化，不会埋没在聊天记录中。
4. `OpenClaw-native Operation`
   仓库设计为在 OpenClaw 风格的 self-hosted 环境中运行，也支持手动聊天驱动的 initialization。

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
├── pyproject.toml
├── config/
│   ├── action-templates/
│   ├── context/
│   └── profiles/
├── docs/
│   ├── README.md
│   ├── core-refactor.md
│   ├── ref/
│   │   ├── architecture.md
│   │   └── runtime.md
│   ├── guide/
│   │   └── openclaw-compose.md
│   ├── archive/
│   └── validation/
│       └── phase-<n>-report.md
├── scripts/
│   ├── phase{1-4}_loading.sh       # 确定性 I/O
│   ├── phase{1-4}_thinking.sh      # LLM 推断
│   ├── register_canonical_root.sh  # 注册共享状态根目录
│   ├── twinbox_orchestrate.sh      # 共享编排 CLI
│   ├── run_pipeline.sh             # 向后兼容 wrapper
│   └── twinbox_paths.sh            # 统一解析 code root / state root
└── runtime/
```

## 快速开始 🚀

1. 阅读 [docs/README.md](docs/README.md)。
2. 阅读 [architecture.md](docs/ref/architecture.md)。
3. 阅读 [core-refactor.md](docs/core-refactor.md)。
4. 如果你想在本地验证邮箱访问权限，运行：
   - `twinbox mailbox preflight --json`
   - 或兼容 wrapper：`bash scripts/preflight_mailbox_smoke.sh --json`
5. 如果你想扩展 runtime 契约，从以下文件开始：
   - [runtime.md](docs/ref/runtime.md)
   - [scheduling.md](docs/ref/scheduling.md)
   - [Action Templates README](config/action-templates/README.md)

### 首次登录排错速查

- `missing_env`：补齐 `MAIL_ADDRESS` 与 IMAP/SMTP 的 host/port/login/pass。
- `imap_auth_failed`：检查用户名密码，或确认服务商是否要求应用专用密码。
- `imap_tls_failed`：优先核对端口与加密组合，常见是 `993 + tls` 或 `143 + starttls/plain`。
- `imap_network_failed`：检查主机名、DNS、容器网络和防火墙。
- `mailbox-connected + warn`：只读 IMAP 已通过，SMTP 在只读模式下仅作提示，不阻塞 Phase 1-4。

## Runtime 未来方向

下一个 runtime 层不会直接克隆 Anthropic 的 `email-agent`。

它将保持本仓库的优势：

- 渐进 validation
- 以 Thread 为中心的 workflow state
- human context plane
- controlled automation gates

并将吸收重要的工程组件：

- `Listener` / `Action` 分离
- `Template` / `Instance` 分离
- Typed Execution Context
- Execution Audit Trail
- 易于扩展的 enable/disable 接口

## 安全边界

- 仅使用应用/客户端专用密码。
- 保持 `.env` 本地化，绝对不要提交它。
- 将 `runtime/` 视为本地运行数据。
- 在证明草稿质量和审批流程有效之前，不要自动发送。
- 不要让用户提供的 Context 静默覆盖邮箱事实。

## 发布说明

该仓库的 `docs/validation/` 下仍包含从真实邮箱研究中生成的本地验证材料。在完全开放之前，你应该审查并清理任何特定于实例的文件和历史记录。

面向开源的架构和模板文档位于 `docs/validation/` 之外，应保持为稳定的公共接口。
