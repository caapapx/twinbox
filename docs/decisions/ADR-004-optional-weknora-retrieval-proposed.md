# ADR-004: Optional WeKnora Retrieval (Proposed)

- **Status**: Proposed — 未接受，不改变ADR-003现行行为
- **Date**: 2026-09-18
- **Related**: [ADR-003](ADR-003-retrieval-spine-and-external-services.md)、[014](../../specs/014-weknora-retrieval-adapter/spec.md)、[013](../../specs/013-semantic-policy-projections/spec.md)

## Context
旧Cursor草案与运维overlay已有WeKnora材料，但TwinBox尚未有对应产品适配器和正式008合同（008已另用）。希望增加长尾检索，不能把邮箱、动态分类或全文搬成第二权威。

## Proposed Decision
保留ADR003 sidecar默认检索，在显式启用时增加自托管、专用KB、最小权限的WeKnora摘录副本。只同步身份与有界原文元数据；KB不存分类/queue/LLM推断；查询join TwinBox派生状态。身份按tenant/account隔离，创建超时先对账，服务失败按同grant回退sidecar。跨KB融合不在首版。

## Acceptance Conditions
管理员接受取舍；验证现场接口/检索前授权/幂等对账能力、专用key/KB、保留删除策略；三十查询Recall@5不劣于基线、零越权且成本可解释。未满足前允许本地禁用路径/mock开发，不启用或替换默认拓扑。

## Alternatives / Consequences
继续sidecar是合法默认；全量迁库、retag动态分类、直接复用制度KB均拒绝。新增索引运维、删除对账和网络失败成本须计入ROI。退回关闭开关不自动清空旧KB材料，删除另走批准策略。无需修订全文/凭据宪章。
