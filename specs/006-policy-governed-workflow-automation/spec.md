# Feature Specification: Policy-Governed Workflow Automation

**Feature Directory**: `006-policy-governed-workflow-automation`

**Created**: 2026-09-04

**Status**: Draft / Planned（依赖 [ADR-002](../../docs/decisions/ADR-002-read-only-to-policy-governed-execution.md) 与 constitution I 1.2.0；实现前代码保持只读默认）

**Input**: 管理员预授权范围内的全自动流转（转发/推进）；未命中策略转人工；审计与幂等。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 策略命中后自动执行 (Priority: P1)

管理员声明流程、允许的目标范围与动作类型。系统识别匹配邮件事件后，在策略内自动执行（例如转发至允许的角色解析结果），并写审计。

**Why this priority**: 会议明确要减少人工中转；且必须可验收安全边界。

**Independent Test**: 策略内夹具执行成功且有审计；策略外夹具拒绝，无副作用。

**Acceptance Scenarios**:

1. **Given** 匹配策略的事件与可解析目标，**When** 执行，**Then** 动作完成一次，审计含策略版本、目标、幂等键。
2. **Given** 同类事件重放相同幂等键，**When** 再次执行，**Then** 不产生第二次副作用。
3. **Given** 事件不匹配任何策略，**When** 评估，**Then** 转人工/拒绝，无发送。

### User Story 2 - 确认通道与超时 (Priority: P2)

对需要确认的步骤，经外部通道（如 iFlyChat）收集结构化确认；超时升级或停机，通道失败不得当作已确认。

**Why this priority**: 会议包含确认闭环；通道是外部依赖。

**Independent Test**: mock 通道超时与失败路径；断言状态机停在可恢复态。

**Acceptance Scenarios**:

1. **Given** 确认请求已发出，**When** 收到「无问题」，**Then** 按策略推进下一步。
2. **Given** 通道超时，**When** 到达超时阈值，**Then** 升级或人工接管，不自动假装确认。

### User Story 3 - 目标解析失败停机 (Priority: P1)

目标无法唯一解析到策略允许范围时停止，暴露诊断，不扩大收件人。

**Why this priority**: 防止「模型自行选人」越权。

**Independent Test**: 歧义收件人夹具 → 无发送 + 诊断。

**Acceptance Scenarios**:

1. **Given** 多个候选均在允许范围但无法消歧，**When** 评估，**Then** 不发送并请求人工选择。
2. **Given** 模型提议的目标在允许范围外，**When** 评估，**Then** 拒绝。

## Edge Cases

- 部分成功（已转发、确认失败）：补偿/人工指令必须可查。
- 策略被禁用：进行中实例停止新的自动步骤。
- 凭据/SMTP 失败：`ok=false` + recovery，不标记流程成功。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST execute mailbox/outbound side effects only under an explicit Automation Policy (process, target scope, action types).
- **FR-002**: Model confidence MUST NOT authorize execution without policy match.
- **FR-003**: System MUST record audit events for every side-effect attempt (success or failure).
- **FR-004**: System MUST enforce idempotency keys for side effects.
- **FR-005**: On target ambiguity, policy miss, or dependency failure, System MUST stop auto-progress and expose recovery.
- **FR-006**: Confirmation channel failures MUST NOT be treated as positive confirmation.
- **FR-007**: Until this feature is implemented and verified, runtime MUST keep read-only default behavior.

### Key Entities

- **AutomationPolicy**: 流程、范围、动作、版本。
- **ActionAttempt**: 幂等键、结果、审计。
- **ConfirmationRequest**: 外部通道状态机。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 策略外夹具 0 次成功副作用。
- **SC-002**: 相同幂等键重放副作用次数 ≤ 1。
- **SC-003**: 审计可追溯每次成功转发至策略版本与目标。
- **SC-004**: 确认通道超时用例 100% 进入人工/升级态而非「已确认」。

## Assumptions

- SMTP/写邮箱能力与确认通道的具体厂商适配在 plan 阶段选定；本 spec 不绑定单一 IM 产品为唯一实现。
- 样例「财务收入确认 → 项目经理」仅作语义包+策略夹具。

## Out of Scope

- 无策略的完全自主发送。
- 修改 Agent OS 内部工作流引擎。
- 替代 `002` 正确性修复。
