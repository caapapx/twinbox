# Feature Specification: Semantic Context and Event Intelligence

**Feature Directory**: `003-semantic-context-event-intelligence`

**Created**: 2026-09-04

**Status**: Draft / Planned

**Input**: 通用事件理解与声明式语义包；企业/个人场景解耦。决策见 [ADR-001](../../docs/decisions/ADR-001-product-boundary-and-semantic-decoupling.md)。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 装载语义包后理解邮件事件 (Priority: P1)

操作者装载一个声明式 Semantic Pack。系统从已同步邮件产出带稳定引用的事件记录（类型、字段、证据），不把组织树或「项目经理」硬编码进引擎。

**Why this priority**: 无通用事件层则周报运营与流程自动化无法复用同一内核。

**Independent Test**: 用样例语义包 + 构造邮件（无真实 IMAP）断言事件类型、字段与引用存在，且无正文进入平台向输出。

**Acceptance Scenarios**:

1. **Given** 有效 Semantic Pack 与匹配邮件，**When** 运行事件理解，**Then** 产出事件含稳定 ID、类型、引用与抽取字段。
2. **Given** 更换另一 Semantic Pack（不同事件类型名），**When** 再次运行，**Then** 引擎代码无需为新类型名改核心实体；输出仍为同一 envelope 形状。
3. **Given** 平台向输出，**When** 扫描字段，**Then** 无全文/附件内容。

### User Story 2 - 语义包仅声明式 (Priority: P1)

作者用结构化文件定义实体、关系、分类、关注点、路由条件与动作策略；系统拒绝含可执行代码的包。

**Why this priority**: 声明式边界是安全与可审计前提。

**Independent Test**: 合法 YAML/结构化包加载成功；含脚本或可执行钩子的包被拒绝并返回结构化错误。

**Acceptance Scenarios**:

1. **Given** 仅含声明字段的包，**When** 校验并加载，**Then** 成功并记录包 ID 与版本。
2. **Given** 含任意代码/插件载荷的包，**When** 校验，**Then** 拒绝加载。

### User Story 3 - 场景夹具不污染核心 (Priority: P2)

「交付部周报」「收入确认转办」等仅作为样例包与验收夹具，用于验证抽象，不成为核心模块名。

**Why this priority**: 防止把二次会议纪要直接固化为领域模型。

**Independent Test**: 核心文档/API 无强制依赖这些业务专名；样例包目录可单独加载。

**Acceptance Scenarios**:

1. **Given** 未装载任何企业样例包，**When** 使用最小个人偏好包，**Then** 事件理解仍可运行（范围由包定义）。
2. **Given** 企业样例包，**When** 对照夹具验收，**Then** 行为由包声明解释，而非硬编码分支表。

## Edge Cases

- 包版本升级导致事件类型重命名：旧游标/事件 ID 规则须文档化（兼容或显式迁移）。
- 邮件无法匹配任何事件规则：产出 `unclassified` 或等价显式结果，不静默丢弃证据引用。
- 多包同时装载冲突：按声明的优先级/命名空间解决，冲突进入 diagnostics。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST load versioned declarative Semantic Packs that define entities, relations, classification hints, attention hints, routing conditions, and action-policy *declarations* (no executable code).
- **FR-002**: System MUST emit evidence-backed event records with stable IDs and mail references; platform-facing payloads MUST NOT include full bodies.
- **FR-003**: Event type names and attribute keys MUST be opaque to downstream platforms (versioned map/list), not a frozen six-key enum compiled into consumers.
- **FR-004**: Core engine MUST NOT hard-code organization trees, performance scores, or named enterprise roles as first-class entities.
- **FR-005**: Pack validation MUST reject non-declarative executable content.
- **FR-006**: New tools or additive `data` fields MUST preserve MCP envelope shape (`ok`/`data`/`error`/`recovery_tool`).

### Key Entities

- **SemanticPack**: 版本化声明式领域上下文。
- **EventRecord**: 类型 + 引用 + 抽取字段 + 去重键。
- **MailReference**: 账号/消息/线程稳定引用与有界元数据。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 同一引擎在不改核心实体代码的前提下，可切换至少两个不同语义包并产出合法事件。
- **SC-002**: 平台向输出全文扫描命中数为 0。
- **SC-003**: 含可执行载荷的包 100% 被校验拒绝。
- **SC-004**: 样例企业夹具事件召回与人工标注对照 ≥ 约定阈值（实现阶段在 plan 中量化；默认目标 80%）。

## Assumptions

- 依赖邮件同步与（后续）`001` 数据平面引用能力；本 feature 不实现 SMTP。
- `002` 分析正确性应优先或并行收敛，避免坏解码污染事件质量。
- 文化对比、营销式「智能大脑」不进入本契约。

## Out of Scope

- 自动转发与流程推进（`006`）。
- 组织级周报缺交统计 UI（`004`）。
- 用户三分类投影与 onboarding 问卷（`005`）。
