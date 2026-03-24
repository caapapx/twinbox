# AGENTS.md

## 文档索引规则

| 目录 | 用途 | 命名规则 |
|------|------|----------|
| src/twinbox_core/ | Python 核心库（Phase 1-4、CLI、LLM）| 按模块命名 |
| tests/ | Python 单元测试 | `test_<module>.py` |
| scripts/ | Shell 流水线脚本（phase 加载/思考/合并） | `phase<N>_<step>.sh` |
| config/ | 运行时配置（用户画像、策略、行动模板） | `<name>.yaml` / `<name>.toml` |
| agent/ | TypeScript 扩展契约骨架（spec-first，尚未完整实现） | `*.ts` |
| docs/ref/ | 架构、契约、CLI、运行时参考 | 短名优先，如 `cli.md` |
| docs/guide/ | 操作与集成指南 | `<topic>.md` |
| docs/archive/ | 历史方案、旧评估、废弃记录 | 按主题归档 |
| docs/validation/ | 实例级验证报告（本地数据，不入公开发布） | `phase-N-report.md` |
| docs/assets/ | 图片、静态资源 | 按需 |

## 核心文档入口

- 文档入口：`docs/README.md`
- 架构：`docs/ref/architecture.md`
- 核心重构计划：`docs/core-refactor.md`
- 验证工件契约：`docs/ref/validation.md`
- 编排契约：`docs/ref/orchestration.md`
- 运行时规范：`docs/ref/runtime.md`
- 文档重构计划：`docs/archive/docs-refactor.md`
- 开源 V1 计划（历史归档）：`docs/archive/oss-v1.md`
- Phase 1 intent LLM 改造记录：`docs/archive/reports/phase1-intent-llm.md`
- Phase 2 persona LLM 改造记录：`docs/archive/reports/phase2-persona-llm.md`
- Phase 3 lifecycle LLM 改造记录：`docs/archive/reports/phase3-lifecycle-llm.md`
- Phase 4 value LLM 改造记录：`docs/archive/reports/phase4-value-llm.md`

## 协作约束

1. 所有文档先看 `docs/README.md`，优先并入现有文件，不轻易新增目录或文件
2. 新增文档前先检查是否有可合并的已有文档
3. validation/ 下的内容是实例数据，不应被方案文档引用为"事实"
4. 文档内交叉引用使用相对路径
