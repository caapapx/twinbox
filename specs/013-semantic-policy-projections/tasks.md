# Tasks: 可配置语义与双向证据

**Status**: Planned；实施任务只有取得证据才勾选。路径均相对本仓；Agent OS中`app/`为`apps/control-plane/app/`。

## Format and dependencies
- `Tnnn [USn]`；未标`[P]`不意味着可同时修改。测试先失败，再实现，再回归。
- 不创建分支、不提交、不部署；此前局部本地实施保留；本轮只授权修订方案，产品实施仍暂停，不由旧文案自动恢复。
T001→T002；T003→T004为首个独立修复；T005→T006后T007→T008→T009；T010→T011可在纯函数层独立推进，集成T012依赖T008；T013→T014→T015，最后客户端与回归/现场门。


## Phase — Setup
- [x] T001 核对Cursor待办去重清单与既有A–F证据，记录工作树保护基线到 docs/plans/2026-09-18-cursor-backlog-audit.md（FR-011, FR-012）
- [x] T002 复核 spec/plan/contracts/checklists 与旧constitution，完成只读analyze并记录执行范围到 docs/plans/2026-09-18-execution-log.md（FR-001, FR-008, FR-010）

## Phase — US1
- [x] T003 [US1] 先在 tests/test_semantic_policy.py 写审批误归周报、各type语义命中和无规则回归并观察失败（FR-001, FR-002）
- [x] T004 [US1] 修正 twinbox_core/events.py 与 twinbox_core/rules.py 的每type语义判别，保留无规则与旧调用兼容（FR-001, FR-002）
- [x] T005 [US1] 在 tests/test_semantic_policy.py 先补优先级冲突/非法Pack/三匿名部门包用例（FR-001, FR-002, FR-003）
- [x] T006 [US1] 在 twinbox_core/pack.py、rules.py、events.py、project.py 实现声明式验证、稳定ID/解释与注意力轴投影（FR-001, FR-002, FR-003）

## Phase — US2
- [x] T007 [US2] 先在 tests/test_classification_store.py 写一信多事/同主题不同项目/规则版本切换/跨月未知/撤权用例（FR-004, FR-005, FR-006）
- [x] T008 [US2] 在 twinbox_core/classification_store.py 实现稳定case引用、版本化派生快照/覆盖、锁与原子重算发布（FR-004, FR-005, FR-006）
- [x] T009 [US2] 在 twinbox_core/analyze.py、pulse.py 集成经过验证的证据引用与lineage；不得覆盖人工确认或刷新假时间（FR-005, FR-006, FR-011）

## Phase — US3
- [x] T010 [US3] 先在 tests/test_evidence_contract.py 写共享schema样例、嵌套正文、超限、未知分类、伪造scope等边界负例（FR-007, FR-008, FR-010）
- [x] T011 [US3] 在 twinbox_core/evidence_contract.py 实现出站字段构造与严格观察/反馈验证；先独立纯函数再接现有adapter（FR-007, FR-008, FR-010）
- [x] T012 [US3] 在 tests/test_evidence_contract.py 补稳定游标/并发分页/版本兼容测试，并在 twinbox_core/adapter.py 兼容集成013输出（先保护现有WIP）（FR-007, FR-008, FR-011）
- [x] T013 [US3] 先在 tests/test_feedback.py 写授权/幂等/乱序/冲突/回执不等于done的测试（FR-009, FR-010）
- [x] T014 [US3] 在 twinbox_core/feedback.py 实现提议、人工确认、执行回执的权限复核、revision与审计（FR-009, FR-010）
- [x] T015 [US3] 在 twinbox_core/cli.py、mcp-server.mjs 与 SKILL.md 接入版本化数据工具及授权反馈；不开放聊天改规则（FR-007, FR-009, FR-010）

## Phase — US2
- [x] T016 [US2] 先在 tests/test_semantic_client_projection.py 再在 twinbox_core/cli.py 实现动态标签目录、旧卡片兼容与证据按需展开（FR-003, FR-007, FR-011）

## Phase — Validation
- [x] T017 运行 tests/test_corrective_handoff.py 与既有quick-refresh/queue/window/MCP用例；记录A–F每项证据，不把F日志缺失勾完成（FR-011）
- [x] T018 将匿名案例映射到 tests/fixtures/semantic_policy/，保留旧G/C金标；真实金标由业务负责人在私有基线确认（FR-012）
- [x] T019 执行快照恢复、5k/20k数据规模与读p95对照；结果写 docs/plans/2026-09-18-execution-log.md（FR-006, FR-011, FR-012）
- [ ] T020 在私有评测目录收集至少三类各三次配对时间/成本/纠错，不报告未经实测ROI；docs仅记脱敏结论（FR-012）。**Partial (2026-09-20):** 已与 Agent OS 共用忽略目录 `agent-os-design/tmp/business-value-evaluation-20260920/` 建立三场景×A/B/C预登记、九个待授权槽位与全角色计量字段；邮件候选仅有14个私有历史占位和10个合成项，真实来源/金标/开发-留出划分及全部计量均为 pending，故不构成三类各三次或ROI证据。 共享账本现可由 `agent-os-design/apps/control-plane/tests/evaluations/business_value_ledger.py` 做只输出脱敏聚合的预检；当前结果仍为四项门禁未通过，且该工具不读取来源或计算ROI，故本任务不勾选。

## Phase — Release
- [ ] T021 管理员确认真实Pack/source grant后才启用；显式请求才做239长程回放，证据记 docs/runtime/，本地成功不等于上线（FR-001, FR-010, FR-011）
- [x] T022 执行SpecKit analyze/converge，回填 specs/013-semantic-policy-projections/tasks.md 及总入口状态；只按源码/测试/运行证据关闭任务（FR-007, FR-011, FR-012）

## Requirement coverage
| Requirement | Tasks |
|---|---|
| FR-001 | T002, T003, T004, T005, T006, T021 |
| FR-002 | T003, T004, T005, T006 |
| FR-003 | T005, T006, T016 |
| FR-004 | T007, T008 |
| FR-005 | T007, T008, T009 |
| FR-006 | T007, T008, T009, T019 |
| FR-007 | T010, T011, T012, T015, T016, T022 |
| FR-008 | T002, T010, T011, T012 |
| FR-009 | T013, T014, T015 |
| FR-010 | T002, T010, T011, T013, T014, T015, T021 |
| FR-011 | T001, T009, T012, T016, T017, T019, T021, T022 |
| FR-012 | T001, T018, T019, T020, T022 |

## Independent validation and MVP
各US的独立验证见spec.md；先共享基础与安全门，再按顺序实施。本地mock、可选context联调与live gates分开报告。运行态不可用时保留未完成项，不用文档勾选替代交付。

## Scheduling clarification — 2026-09-18

以上任务ID、顺序及勾选保持；仅在明确恢复所选范围后执行，不是AgentOS跨场景业务验证的前置清单。专业Agent由各自owner维护，不因双仓计划合并而变成本feature实现范围。平台价值实验引用同一BV记录，不重复建设评测引擎；真实入库/现场操作继续遵循原独立gate。

## Phase 1: Convergence
- [ ] T023 已补齐离线 TB13 清单与报告 harness：14 个无正文/附件/locator 的 opaque 私有历史占位 + 10 个确定性合成分类场景，逐例输出 classification/evidence/correction/failure；历史源材料、签字金标及其真实复跑继续等待业务负责人确认，suite 固定 `decision_eligible=false`，不以三个 Pack 配置文件或本地合成通过替代二十四案例验收（SC-003, plan: G1/24-case scope）(partial)
- [x] T024 冻结可比较的旧读取基线：同机同 fixture 下对 raw classification snapshot / semantic single-case projection 各采样 100 次，分布与 p95 比值归档至 docs/plans/2026-09-20-013-read-baseline.json；仅关闭本地合成 1.2 倍读取门（plan: Performance Goals）
