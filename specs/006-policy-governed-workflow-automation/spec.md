# Feature Specification: Policy-Governed Workflow Automation

**Feature Directory**: `006-policy-governed-workflow-automation`

**Created**: 2026-09-04

**Status**: Local implementation verified（dry-run + HITL token；未部署、未操作真实邮箱；依赖 [ADR-002](../../docs/decisions/ADR-002-read-only-to-policy-governed-execution.md)、[ADR-003](../../docs/decisions/ADR-003-retrieval-spine-and-external-services.md) 与 constitution I 1.2.0）

**Implemented local increment (v0.3 dry-run + HITL)**: 提案引擎、审计 jsonl、确认卡片 payload 与短时 confirmation token。**无 SMTP、无写邮箱**；FR-007 只读默认保持。通道仍由宿主 webhook 承担，TwinBox 不投递。

**HITL confirmation token (implemented locally)**: 复用 proposal JSON，生成短时单次 `ctk_` token；token 只存 hash，card 返回原 token；返回 token 的工具回合必须停止，等待后续人类消息；payload hash 改变、过期、重放或篡改均不能确认。状态机到 `confirmed` 后明确落入 `execution.status=blocked_read_only`，本增量**没有** `executing` 转移、没有 SMTP 或真实邮箱副作用。

**Input**: 管理员预授权范围内的全自动流转（转发/推进）；未命中策略转人工；审计与幂等。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 策略命中后生成提案 (Priority: P1)

管理员声明流程、允许的目标范围与动作类型。本增量识别匹配后**生成提案与审计**，不发送邮件。完整自动执行留待后续增量。

**Why this priority**: 会议明确要减少人工中转；且必须可验收安全边界。

**Independent Test**: 策略内夹具产生一条提案且有审计；策略外夹具 0 提案，无邮箱副作用。

**Acceptance Scenarios**:

1. **Given** 匹配策略的事件与可解析目标，**When** 评估，**Then** 产出一条提案，审计含策略版本、目标、幂等键。
2. **Given** 同类事件重放相同幂等键，**When** 再次评估，**Then** 不新增第二条 proposed 记录。
3. **Given** 事件不匹配任何策略，**When** 评估，**Then** 提案列表为空，无发送。

### User Story 2 - 确认通道与超时 (Priority: P2)

对需要确认的步骤，经外部通道（如 chat webhook）收集结构化确认；超时升级或停机，通道失败不得当作已确认。

**Why this priority**: 会议包含确认闭环；通道是外部依赖。

**Independent Test**: mock 通道超时与失败路径；断言状态机停在可恢复态。

**Acceptance Scenarios**:

1. **Given** 确认请求已发出，**When** 后续人类回合带回有效 token，**Then** 仅将本地 proposal 转为 `confirmed` + `blocked_read_only`，不推进真实邮箱步骤。
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

- **FR-001**: Mailbox/outbound side effects MUST occur only under an explicit Automation Policy. **This increment MUST NOT send or write mail**; it MUST emit proposals, audit records, and card payloads only.
- **FR-002**: Model confidence MUST NOT authorize execution without policy match.
- **FR-003**: System MUST record audit events for every side-effect attempt (success or failure).
- **FR-004**: System MUST enforce idempotency keys for side effects.
- **FR-005**: On target ambiguity, policy miss, or dependency failure, System MUST stop auto-progress and expose recovery.
- **FR-006**: Confirmation channel failures MUST NOT be treated as positive confirmation.
- **FR-007**: Runtime MUST keep read-only default behavior for this increment.
- **FR-008**: A confirmation token MUST be short-lived, single-use, bound to the canonical draft-payload hash, and stored only as a hash in local proposal state/audit.
- **FR-009**: Token issuance MUST emit a machine-readable stop-turn instruction. Expiry, replay, invalid token, and payload tamper MUST NOT transition to `confirmed` or `executing`; this increment has no `executing` transition.

### Key Entities

- **AutomationPolicy**: 流程、范围、动作、版本。
- **ActionAttempt**: 幂等键、结果、审计。
- **ConfirmationRequest**: 外部通道状态机。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 策略外夹具 0 条提案、0 次邮箱副作用。
- **SC-002**: 相同幂等键重放不新增第二条 proposed 成功记录。
- **SC-003**: 审计可追溯每条提案至策略版本与目标（或 `needs_human`）。
- **SC-004**: 确认通道超时/失败用例 100% 保持未确认，不得标为 confirmed。

## Assumptions

- 本增量不接 SMTP / 飞书 SDK；Twinbox 只产 card payload（ADR-003）。
- 样例「财务收入确认 → 项目经理」仅作语义包+策略夹具。

## Out of Scope

- 无策略的完全自主发送。
- 修改 Agent OS 内部工作流引擎。
- 替代 `002` 正确性修复。
