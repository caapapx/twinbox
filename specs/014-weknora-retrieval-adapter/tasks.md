# Tasks: WeKnora可选检索

**Status**: Partially implemented locally；实施任务只有取得证据才勾选。T001–T007 仅完成默认关闭的 fake-provider 合同，现场 gate 与人工评测仍未完成。路径均相对本仓；Agent OS中`app/`为`apps/control-plane/app/`。

## Format and dependencies
- `Tnnn [USn]`；未标`[P]`不意味着可同时修改。测试先失败，再实现，再回归。
- 不创建分支、不提交、不部署；2026-09-20已按用户继续请求恢复 **仅本地、默认关闭、fake-provider** 的T001–T004。该恢复不授权真实邮箱读取、真实KB/key/API、网络写入或现场发布；此前WIP仍保留。
T001→T002→T003→T004；T005→T006依赖013分类索引；T007故障恢复；T008现场gate未过时T009可用mock先做，T010不得开始。


## Phase — Setup
- [x] T001 完成 specs/014-weknora-retrieval-adapter/contracts/ 与 ADR004 Proposed设计复核，不提前修改ADR003 Accepted决定（FR-001, FR-010；2026-09-20本地mock放行，非ADR接受）

## Phase — US1
- [x] T002 [US1] 先在 tests/test_weknora_sync.py 写有界原文来源、scope/ID缺失冲突、同内容skip/变更update/POST超时对账测试（FR-002, FR-003, FR-004；fake provider，2026-09-20）
- [x] T003 [US1] 在 twinbox_core/weknora.py 实现能力port、稳定映射、journal、单写者幂等与异步parse状态（FR-002, FR-003, FR-004, FR-005；本地端口，无真实REST实现）
- [x] T004 [US1] 在 twinbox_core/config.py 与 cli.py 加默认关闭配置、显式同步与有界诊断；保护用户WIP（FR-001, FR-005, FR-009；HTTP factory 与 `weknora revoke` 已接线，三重门未开不能开启真实网络同步）

## Phase — US2
- [x] T005 [US2] 先在 tests/test_weknora_search.py 与 test_weknora_security.py 写授权预过滤/跨月未知/score来源/超时回退/撤权矩阵（FR-006, FR-007, FR-008, FR-009；fake-provider本地合同，2026-09-20；非真实检索验收）
- [x] T006 [US2] 在 twinbox_core/weknora.py、select.py 集成013分类索引、映射join与受同grant约束的sidecar回退（FR-006, FR-007, FR-008, FR-009；默认关闭、本地fake-provider，2026-09-20；不调用真实API）
- [x] T007 [US2] 在 tests/test_weknora_sync.py 补崩溃/并发/映射丢失/多写者隔离/撤权删除失败恢复并实现对应路径（FR-004, FR-005, FR-006, FR-010；fake-provider本地合同，2026-09-20；现场gate未过）

## Phase — US3
- [ ] T008 [US3] 取得ADR接受、专用KB/key授权、现场API能力和保留策略；只将脱敏能力矩阵写 specs/014-weknora-retrieval-adapter/research.md（FR-010） 当前已建立脱敏核验模板 `research.md`；ADR、授权、现场能力与保留策略仍为 pending，未勾选。
- [ ] T009 [US3] 在 tests/evaluations/weknora_retrieval.py 建三十条匿名人工标注查询对照；关键词/语义/分类分别统计Recall@5、延迟和成本（FR-011；2026-09-20已完成不连真实服务的30条强制形状、分组指标、零越权/基线gate与匿名fixture校验harness；fixture和runner结果的`query_id`/`mail_ref`均拒绝邮箱、路径等非opaque locator，synthetic dry-run会明确拒绝作为启用/ROI结论；2026-09-21 起 `human_gold` 仍不足以 `decision_eligible`：ADR-004/专用KB/最小权限key/retention/检索前ACL 须各有不透明修订号，pending/unassigned/unavailable 或省略均 fail-closed，且 `roi_eligible` 恒为 false；真实匿名人工金标与现场 gate 仍缺，故本任务不勾选）
- [ ] T010 [US3] 仅在前述live gates通过后做小样本索引/检索与关开关回退验收，证据写 docs/runtime/，保留sidecar（FR-001, FR-009, FR-011）

## Phase — Release
- [x] T011 已同步修订仓外 `weknora-ops/overlays/twinbox.md` 的旧008/身份/映射表述：明确014、scope/account/mail_ref、`weknora-sync.json` 与默认关闭fake-provider边界；凭据不入合同。此文档更正不代表ADR接受、真实KB/API、邮件写入或发布（FR-003, FR-010；2026-09-20）
- [x] T012 执行SpecKit analyze/converge并回填 specs/014-weknora-retrieval-adapter/tasks.md；以显式014 selector完成一致性检查，无新增收敛任务；mock通过不勾现场gate（FR-001, FR-010, FR-011；2026-09-20）

## Requirement coverage
| Requirement | Tasks |
|---|---|
| FR-001 | T001, T004, T010, T012 |
| FR-002 | T002, T003 |
| FR-003 | T002, T003, T011 |
| FR-004 | T002, T003, T007 |
| FR-005 | T003, T004, T007 |
| FR-006 | T005, T006, T007 |
| FR-007 | T005, T006 |
| FR-008 | T005, T006 |
| FR-009 | T004, T005, T006, T010 |
| FR-010 | T001, T007, T008, T011, T012 |
| FR-011 | T009, T010, T012 |

## Independent validation and MVP
各US的独立验证见spec.md；先共享基础与安全门，再按顺序实施。本地mock、可选context联调与live gates分开报告。运行态不可用时保留未完成项，不用文档勾选替代交付。

## Scheduling clarification — 2026-09-18

以上任务ID、顺序及勾选保持；仅在明确恢复所选范围后执行，不是AgentOS跨场景业务验证的前置清单。专业Agent由各自owner维护，不因双仓计划合并而变成本feature实现范围。平台价值实验引用同一BV记录，不重复建设评测引擎；真实入库/现场操作继续遵循原独立gate。
