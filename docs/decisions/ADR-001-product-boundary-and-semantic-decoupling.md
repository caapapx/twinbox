# ADR-001: Product Boundary and Semantic Decoupling

- **Status**: Accepted
- **Date**: 2026-09-04
- **Deciders**: product + engineering (post-delivery repositioning review)
- **Supersedes**: informal “enterprise email assistant / intelligent brain” marketing framing as architecture language
- **Related**: constitution Delivery Surface; `specs/003-semantic-context-event-intelligence`

## Context

SpecKit 在开发中途插入。半年 as-built 能力是单邮箱只读 MCP Skill（见 `specs/000-as-built-mcp-baseline`）。二次定位会议提出周报运营、流程中转、企业/个人通用等方向。若把组织树、绩效、项目经理等硬编码进核心，会把场景误当成引擎，并与「企业/个人均可定制」冲突。

## Decision

1. Twinbox 核心冻结为：**邮件事件流上的理解、注意力决策输入、证据引用，以及（经 ADR-002）策略约束的流程编排能力**。
2. **领域语义与核心引擎解耦**。企业组织关系、个人偏好、周报规则、审批角色等进入可版本化的 **Domain Semantic Pack**（声明式结构化文件），不进入核心实体模型。
3. Semantic Pack **仅声明式**：可描述实体、关系、分类、关注点、路由条件、动作策略；**禁止**携带任意代码或未沙箱插件。
4. 会议中的具体业务（交付部周报、收入确认转项目经理等）用作**样例语义包与验收夹具**，用于场景驱动抽象发现与契约验证；不写成核心领域名词。
5. 「反向训练架构」用语废弃；改为：**以场景驱动抽象、以实例验证契约**（除非另有明确的模型训练合同）。

## Consequences

- 新增 feature 必须说明依赖的通用机制 vs 语义包实例。
- `001` 数据平面输出属性轴为版本化 opaque map，不得把某一企业 taxonomy 锁进平台 schema。
- 个人与企业同属「语义包可替换」；首期验证材料可偏企业，但不把企业实体写进引擎。
- 旧文档中的 monolith 发送/草稿概念保持 archive，不自动复活。
