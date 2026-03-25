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
- 语义规则引擎：`docs/ref/routing-rules.md`
- 文档重构计划：`docs/archive/docs-refactor.md`
- 开源 V1 计划（历史归档）：`docs/archive/oss-v1.md`
- Phase 1 intent LLM 改造记录：`docs/archive/reports/phase1-intent-llm.md`
- Phase 2 persona LLM 改造记录：`docs/archive/reports/phase2-persona-llm.md`
- Phase 3 lifecycle LLM 改造记录：`docs/archive/reports/phase3-lifecycle-llm.md`
- Phase 4 value LLM 改造记录：`docs/archive/reports/phase4-value-llm.md`（含 2026-03-25 recipient_role 全链路降权实现）

## 协作约束

1. 所有文档先看 `docs/README.md`，优先并入现有文件，不轻易新增目录或文件
2. 新增文档前先检查是否有可合并的已有文档
3. validation/ 下的内容是实例数据，不应被方案文档引用为"事实"
4. 文档内交叉引用使用相对路径
5. **新增或移动**文档路径时，同步更新**可发现性**（至少一处，避免零索引）：
   - 常用契约/指南：在 `docs/README.md` 的 **Read first** 或 **Layout** 增删一条链接，和/或在本文 **核心文档入口** 增删一条；或
   - 落在已有子包/子目录时：更新该目录的 **README.md**（例如 `openclaw-skill/README.md`、`docs/guide/` 下说明）
   - **可不上抬到 Read first 的情况**：纯 `docs/archive/` 深埋归档、`docs/validation/` 实例报告，只需在主题文档或子索引中链入即可
6. **验证通过后的 Git 落地**（与「只描述已完成」区分）：在完成本次任务约定校验且**明确成功**时，代理**应当**提交；在环境允许且用户未禁止时**应当**推送。
   - **高置信度门槛**：已对变更范围跑过约定检查（例如相关 `pytest`、或任务指定的 smoke/脚本），失败已处理或已说明为何不跑
   - **提交**：`git add` 仅包含本次任务相关改动；提交信息遵守 `type: short description`；推送前用 `git status` 确认无意外未提交文件
   - **推送**：具备 `git` 写权限与网络、且用户**未**要求「勿推送 / 仅本地 / draft」时，执行 `git push` 到当前跟踪的远程分支（本仓库约定为 `master`）
   - **环境受限**：沙箱禁用网络、无凭据、或推送被拒时，说明原因并保留本地 commit，由用户手动 `git push`
   - **禁止**：对共享分支 `git push --force`；非用户明确要求不擅自 `git commit --no-verify` / 绕过 hook
