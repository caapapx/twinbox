# Feature Specification: Weekly Report Operations

**Feature Directory**: `004-weekly-report-operations`

**Created**: 2026-09-04

**Status**: Draft / Planned

**Input**: 周报成批监控与汇总；只产事实证据，不打绩效分。依赖语义包中的周期/群体定义（见 `003`）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 周期提交事实清单 (Priority: P1)

管理者（或代理）查看某周期内：谁已提交、准时、迟交、缺交、重复或无法归属。每条结论带邮件引用或「证据不足」标记。

**Why this priority**: 会议核心运营痛点；且必须与「绩效打分」解耦。

**Independent Test**: 给定权威名单 + 截止时间 + 构造邮件集，断言状态分类与引用正确；无绩效分数字段。

**Acceptance Scenarios**:

1. **Given** 名单与截止时间，**When** 运行合规汇总，**Then** 每人得到 submitted/on_time/late/missing/duplicate/unattributable 之一（或显式未知）。
2. **Given** 输出报告，**When** 检查字段，**Then** 无 score/rank/绩效评价字段。
3. **Given** 仅在单一邮箱未找到邮件，**When** 判定 missing，**Then** 仅在名单覆盖与邮箱覆盖已声明充分时成立；否则标记证据不足而非断言「未写周报」。

### User Story 2 - 按语义包聚合 (Priority: P2)

汇总按 Semantic Pack 中的分组声明聚合（组/树状开关），而不是引擎内置组织树类型。

**Why this priority**: 落实语义解耦。

**Independent Test**: 两套不同分组声明的包对同一邮件集产出不同聚合桶，引擎无硬编码部门名。

**Acceptance Scenarios**:

1. **Given** 包定义两组与开关，**When** 汇总，**Then** 按组输出计数与成员状态。
2. **Given** 关闭某组开关，**When** 汇总，**Then** 该组不进入报告。

### User Story 3 - 内容摘要可选且有界 (Priority: P3)

可对已提交周报生成有界要点摘要供管理者浏览；摘要不替代合规事实层。

**Why this priority**: 会议提到智能汇总，但次于事实监控。

**Independent Test**: 摘要长度有界；平台向输出仍无全文。

## Edge Cases

- 一人多封：duplicate + 选用规则由包声明。
- 跨邮箱：须声明观察邮箱集合；覆盖不全不得假装全员监控。
- 「不再需要抄送支撑」：仅当覆盖与身份匹配经验证后才能写进成功标准；此前为研究假设。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept an expected population, period, and deadline from a Semantic Pack (or equivalent declarative input).
- **FR-002**: System MUST classify submission facts with evidence references or explicit insufficiency.
- **FR-003**: System MUST NOT auto-generate performance scores, rankings, or personnel evaluations.
- **FR-004**: Aggregation MUST follow pack-declared grouping; core MUST NOT require a built-in org-tree type.
- **FR-005**: Platform-facing outputs MUST remain reference/bounded-excerpt only.

### Key Entities

- **ReportingPeriod**: 周期与截止。
- **ExpectedMember**: 预期提交者身份引用。
- **SubmissionFact**: 状态 + 证据引用 + 不确定性。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 在标注夹具上状态分类准确率可度量（实现 plan 定阈值；默认 ≥ 90% 对可归属样本）。
- **SC-002**: 任何合规报告 schema 不含绩效分/排名字段（自动化 schema 检查）。
- **SC-003**: 证据不足案例 100% 显式标记，不得静默标为 missing。

## Assumptions

- 权威名单与日历来自组织系统或语义包维护，不由模型臆造。
- 当前 `twinbox_weekly` / extract profile 不是本 feature 的实现。

## Out of Scope

- 自动绩效打分。
- 自动转发催交邮件（可在 `006` 另议，须策略授权）。
