# ADR-004: Optional WeKnora Retrieval

- **Status**: Accepted — 2026-09-21 owner 确认，2026-09-22 写入本记录
- **Date**: 2026-09-18（提议）/ 2026-09-22（接受记录）
- **Deciders**: owner（grill 2026-09-21 Q1）
- **Related**: [ADR-003](ADR-003-retrieval-spine-and-external-services.md)、[014](../../specs/014-weknora-retrieval-adapter/spec.md)、[013](../../specs/013-semantic-policy-projections/spec.md)、[retention](../../specs/014-weknora-retrieval-adapter/retention.md)

## Context
旧Cursor草案与运维overlay已有WeKnora材料，但TwinBox尚未有对应产品适配器和正式008合同（008已另用）。希望增加长尾检索，不能把邮箱、动态分类或全文搬成第二权威。

## Decision
保留 ADR-003 sidecar 默认检索。显式启用时，才增加自托管、专用 KB、最小权限的 WeKnora 摘录副本。只同步身份与有界原文元数据；KB 不存分类、queue 或 LLM 推断；查询 join TwinBox 派生状态。身份按 scope/account 隔离，创建超时先对账，服务失败按同一 grant 回退 sidecar。跨 KB 融合不在首版。

接受本决策不打开运行时开关。`weknora.enabled` 与配置项 `adr_004_accepted` 仍须单独设置；两者缺一，现场同步不发起网络。

## Enablement still closed
现场小样本还要：一条已列入 source grant 的摘录、文档级授权过滤、关开关后的 sidecar 回退证据，以及三十条人工金标。未满足前只保留默认关闭路径与 mock，不替换默认检索拓扑。

## Alternatives / Consequences
继续sidecar是合法默认；全量迁库、retag动态分类、直接复用制度KB均拒绝。新增索引运维、删除对账和网络失败成本须计入ROI。退回关闭开关不自动清空旧KB材料，删除另走批准策略。无需修订全文/凭据宪章。
