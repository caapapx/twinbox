# Feature Specification: Attention Policy and Onboarding

**Feature Directory**: `005-attention-policy-onboarding`

**Created**: 2026-09-04

**Status**: Implemented / verified locally

**Input**: 轻量配置与用户可见注意力投影；紧急度与行动性分轴，避免互斥三分类本体。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 轻量 onboarding 写入语义包 (Priority: P1)

新用户回答少量核心问题（日常需审批什么、特别关注什么、额外留意方向）。制度/通告/福利类可跳过并由默认规则归入参考类。结果写入版本化 Semantic Pack，而非散落 prompt。

**Why this priority**: 会议要求轻量；且配置必须可审计可版本化。

**Independent Test**: 完成问卷后磁盘上出现合法声明式包；再次 sync/分析可读取该包。

**Acceptance Scenarios**:

1. **Given** 用户完成最小问卷，**When** 保存，**Then** 生成/更新 Semantic Pack 版本。
2. **Given** 用户跳过通告类选项，**When** 应用默认，**Then** 通告类默认进入 reference 投影（可配置覆盖）。

### User Story 2 - 用户可见三投影 (Priority: P1)

用户看到 `action_required`、`watch`、`reference` 投影。紧急度、行动性、关注度、敏感度为独立轴；允许「紧急但无需回复」「可行动但不紧急」等组合。

**Why this priority**: 纠正纪要中互斥三分类的语义缺陷。

**Independent Test**: 构造线程分别命中各组合，断言投影与轴值一致且可解释（含证据/规则依据）。

**Acceptance Scenarios**:

1. **Given** 当天必须审批的线程，**When** 投影，**Then** 进入 `action_required` 且 urgency 高。
2. **Given** 重要但无需立刻行动的线程，**When** 投影，**Then** 可进入 `watch` 而非强制 `action_required`。
3. **Given** 普适制度邮件，**When** 投影，**Then** 默认 `reference`，且每条带触发依据。

### User Story 3 - 与正确性分析共存 (Priority: P2)

投影消费 `002` 修复后的 pending/urgent 信号；本 feature 不重开 MIME/join bug 范围。

**Why this priority**: 避免合同膨胀。

**Independent Test**: 文档与验收引用 `002`；本目录任务不复制 MIME 解码工作。

### User Story 4 - 等待方与截止时间可选轴 (Priority: P2)

投影可按**可选轴**呈现两条附加信息：**等待方（waiting party）**与**截止时间（deadline）**。二者均可缺省；一旦分析或包提供取值，该值即携带 `evidence_refs` 回溯到具体邮件证据。本 story 复用既有单次分析产出，**不新增分析 LLM 调用**。

**Why this priority**: 这两条轴增强可解释性，但非最小配置所必需；不新起分析调用以免膨胀合同。

**Independent Test**: 分析行携带 `waiting_on` / `deadline`（或包声明对应值）时，投影项输出带 `evidence_refs`；缺省时投影项不出现这两条轴，也不报错。

**Acceptance Scenarios**:

1. **Given** 分析对某线程声明 `waiting_on`，**When** 投影，**Then** 等待方出现在该项且携带对应 `evidence_refs`。
2. **Given** 分析对某线程声明 `deadline`，**When** 投影，**Then** 截止时间出现在该项且携带对应 `evidence_refs`。
3. **Given** 分析未提供任一可选轴，**When** 投影，**Then** 该项不包含这两条轴且无额外提示。

## Edge Cases

- 无语义包：使用安全默认（偏 reference，避免误标 urgent）。
- 规则与 LLM 冲突：声明式硬约束优先，冲突写入 diagnostics。
- 可选轴（等待方 / 截止时间）缺省：不投影这两条轴，不报错、不触发额外分析。
- 可选轴取值：必须可携带 `evidence_refs`；无证据时不杜撰，沿用现有 `evidence_basis` 语义。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support lightweight onboarding that writes a declarative Semantic Pack.
- **FR-002**: System MUST expose user-facing projections `action_required` / `watch` / `reference` without treating them as a universal exclusive mail ontology.
- **FR-003**: Urgency, actionability, interest, and sensitivity MUST be modelable as separate axes.
- **FR-004**: Each projected item MUST carry evidence or rule rationale.
- **FR-005**: Defaults for institutional/broadcast mail MAY classify as `reference` when user skips configuration.
- **FR-006**: System MAY expose an optional `waiting party` axis; a value supplied by analysis or a pack MUST be able to carry `evidence_refs`.
- **FR-007**: System MAY expose an optional `deadline` axis; a value supplied by analysis or a pack MUST be able to carry `evidence_refs`.
- **FR-008**: An induced taxonomy is a draft until the owner confirms it into the pack. Query assignment reads only a live pack taxonomy and MUST NOT call a model. At most 12 categories plus `other`. A draft run stops on stable batches, held-out other at or below 15%, or an exhausted budget. Nightly drift records a note and does not replace the live list.

### Key Entities

- **AttentionProjection**: 用户可见桶。
- **OnboardingAnswers**: 问卷结果 → 包字段映射。
- **AxisValues**: 独立轴取值。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 用户可在 ≤5 个核心问题内完成可用初始配置。
- **SC-002**: 标注夹具上投影可解释率 100%（每条有依据字段）。
- **SC-003**: 「紧急且无需回复」夹具不被强制标为 pending reply。

## Assumptions

- 依赖 `003` 包机制；当前 `profile_notes`/`calibration_notes` 可作为过渡输入但不是终态。
- `002` 正确性合同保持独立。

## Out of Scope

- 复杂画像、工时系统。
- 自动发送催办（`006`）。
