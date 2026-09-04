# ADR-002: Read-Only Default vs Policy-Governed Execution

- **Status**: Accepted
- **Date**: 2026-09-04
- **Deciders**: product + engineering (post-delivery repositioning review)
- **Amends**: constitution Principle I（原「绝对禁止一切邮箱写操作」）
- **Related**: `specs/006-policy-governed-workflow-automation`; constitution Security Boundaries

## Context

原 constitution I 将真实邮箱 send / move / delete / archive / flag 全部拒绝。会议要求流程类邮件「自动识别目标并完成流转」（含自动转发与确认后推进）。产品选择：**全自动执行**，但授权模型为 **scoped policy**——仅管理员预先批准的流程、收件人范围与动作类型可自动执行；未命中策略转人工。

这是架构边界变更，不能当作普通 feature 悄悄绕过只读原则。

## Decision

1. **默认读路径仍为只读 IMAP**。未挂载 Automation Policy 时，系统不得对真实邮箱执行写操作。
2. **外部副作用属于独立执行域**，仅在显式 Automation Policy 授权下允许，且必须同时满足：
   - 流程 ID / 策略版本可解析；
   - 目标落在允许范围；
   - 动作类型在允许集合内；
   - 幂等键防止重复副作用；
   - 审计记录可追溯；
   - 失败或低置信度目标解析时**停止自动推进**并暴露恢复路径。
3. **LLM 置信度不得单独构成授权**。模型可提议目标与动作；执行门禁是策略匹配。
4. 通知/确认通道（如 iFlyChat）是外部依赖，须在 `006` 中单独契约化；通道不可用时不得静默当作「已确认」。
5. 迁移：在 `006` 实现并验收前，代码路径保持与旧只读行为一致；修宪不等于功能已上线。

## Consequences

- Constitution I 与 Security Boundaries 改为分层表述（见 1.2.0）。
- `001` v1 仍可不包含邮箱写回；写动作落在 `006`。
- 回滚：关闭所有 Automation Policy / 卸载执行工具后，行为回到纯只读。
- 风险：误配策略可导致错误转发；须强制审计、最小权限目标范围与人工接管。
