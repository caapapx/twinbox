# Feature Specification: Attention Policy and Onboarding

**Feature Directory**: `005-attention-policy-onboarding`

**Created**: 2026-09-04

**Status**: Draft / Planned

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

## Edge Cases

- 无语义包：使用安全默认（偏 reference，避免误标 urgent）。
- 规则与 LLM 冲突：声明式硬约束优先，冲突写入 diagnostics。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support lightweight onboarding that writes a declarative Semantic Pack.
- **FR-002**: System MUST expose user-facing projections `action_required` / `watch` / `reference` without treating them as a universal exclusive mail ontology.
- **FR-003**: Urgency, actionability, interest, and sensitivity MUST be modelable as separate axes.
- **FR-004**: Each projected item MUST carry evidence or rule rationale.
- **FR-005**: Defaults for institutional/broadcast mail MAY classify as `reference` when user skips configuration.

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
