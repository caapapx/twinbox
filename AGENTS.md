# AGENTS.md

## 文档索引规则

| 目录 | 用途 | 命名规则 |
|------|------|----------|
| docs/plans/ | 方案、路线图、集成计划 | `<topic>.md` |
| docs/specs/ | 技术规范、合约定义 | `<component>-<aspect>.md` |
| docs/reports/ | 评估报告、质量审计 | `<subject>-evaluation.md` |
| docs/templates/ | 可复用模板 | `<name>-template.md` |
| docs/validation/ | 实例级验证报告（本地数据，不入公开发布） | `phase-N-report.md` |
| docs/assets/ | 图片、静态资源 | 按需 |

## 核心文档入口

- 架构：`docs/architecture.md`
- 渐进验证框架：`docs/plans/progressive-validation-framework.md`
- 多 agent 集成：`docs/plans/gastown-multi-agent-integration.md`
- 运行时规范：`docs/specs/thread-state-runtime.md`
- 开源 V1 计划：`docs/plans/open-source-v1-plan.md`
- Phase 1 intent LLM 改造记录：`docs/reports/phase1-intent-llm-migration.md`
- Phase 2 persona LLM 改造记录：`docs/reports/phase2-persona-llm-migration.md`
- Phase 3 前架构审视：`docs/reports/architecture-review-before-phase3.md`
- Phase 3 lifecycle LLM 改造记录：`docs/reports/phase3-lifecycle-llm-migration.md`
- Phase 4 value LLM 改造记录：`docs/reports/phase4-value-llm-migration.md`

## Agent 角色（gastown 集成后）

| 角色 | gastown 映射 | 职责 |
|------|-------------|------|
| Analyst | Polecat × N | Phase 1-3 子任务执行 |
| Value | Polecat × N | Phase 4 子任务执行 |
| Merger | Refinery | 合并子任务输出为 attention-budget.yaml |
| Monitor | Witness | 监控 polecat 健康、崩溃恢复 |

## 协作约束

1. 所有方案类文档放 docs/plans/，不在 docs/ 根目录散放
2. 新增文档前先检查是否有可合并的已有文档
3. validation/ 下的内容是实例数据，不应被方案文档引用为"事实"
4. 文档内交叉引用使用相对路径
