# AGENTS.md

## 文档索引规则

| 目录 | 用途 | 命名规则 |
|------|------|----------|
| src/twinbox_core/ | Python 核心库（Phase 1-4、CLI、LLM）| 按模块命名 |
| tests/ | Python 单元测试 | `test_<module>.py` |
| scripts/ | Shell 流水线脚本（phase 加载/思考/合并） | `phase<N>_<step>.sh` |
| config/ | 运行时配置（用户画像、策略、行动模板） | `<name>.yaml` / `<name>.toml` |
| agent/ | TypeScript 扩展契约骨架（spec-first，尚未完整实现） | `*.ts` |
| refinery/ | Gastown refinery 集成占位目录（rig/ 为工作目录挂载点） | — |
| docs/plans/ | 方案、路线图、集成计划 | `<topic>.md` |
| docs/specs/ | 技术规范、合约定义 | `<component>-<aspect>.md` |
| docs/reports/ | 评估报告、质量审计 | `<subject>-evaluation.md` |
| docs/templates/ | 可复用模板 | `<name>-template.md` |
| docs/validation/ | 实例级验证报告（本地数据，不入公开发布） | `phase-N-report.md` |
| docs/assets/ | 图片、静态资源 | 按需 |

## 核心文档入口

- 架构：`docs/architecture.md`
- 核心重构计划：`docs/plans/core-refactor-plan.md`
- 渐进验证框架：`docs/plans/validation-framework.md`
- 验证工件契约：`docs/specs/validation-artifact-contract.md`
- 编排契约：`docs/specs/pipeline-orchestration-contract.md`
- 运行时规范：`docs/specs/thread-state-runtime.md`
- Gastown 集成：`docs/plans/gastown-integration.md`
- 开源 V1 计划：`docs/plans/oss-v1-plan.md`
- 项目开发进度（周期性快照）：`docs/reports/development-progress.md`
- Phase 1 intent LLM 改造记录：`docs/reports/phase1-intent-llm-migration.md`
- Phase 2 persona LLM 改造记录：`docs/reports/phase2-persona-llm-migration.md`
- Phase 3 lifecycle LLM 改造记录：`docs/reports/phase3-lifecycle-llm-migration.md`
- Phase 4 value LLM 改造记录：`docs/reports/phase4-value-llm-migration.md`

## Gastown 集成（可选）

twinbox 可以独立运行（使用 `scripts/twinbox` 和 `scripts/twinbox_orchestrate.sh`），也可以通过 Gastown 进行多 agent 编排。

Gastown 集成详见：`docs/plans/gastown-integration.md`

## 协作约束

1. 所有方案类文档放 docs/plans/，不在 docs/ 根目录散放
2. 新增文档前先检查是否有可合并的已有文档
3. validation/ 下的内容是实例数据，不应被方案文档引用为"事实"
4. 文档内交叉引用使用相对路径

## Issue Tracking（可选）

twinbox 支持使用 bd (beads) 进行 issue tracking，但这是可选的。

详见 Gastown 集成文档：`docs/plans/gastown-integration.md`
