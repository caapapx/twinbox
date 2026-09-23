# Implementation Plan: TwinBox 分类权威与证据协议

**Git checkout**: `master`（未新建/切换分支） | **Date**: 2026-09-18 | **Spec**: [spec.md](spec.md)
**Feature selector**: `SPECIFY_FEATURE_DIRECTORY=specs/013-semantic-policy-projections`
**Status**: Draft；已有部分本地分类/协议实现，未实现范围仍按下列计划，完整feature未交付；不把全部模块都称为已实现。

## Summary
先继承旧 Cursor A–F 正确性门，再实现声明式分类、事项级证据与反馈。TwinBox 拥有业务分类；客户端只消费投影，Agent OS 只执行被授权的协作；检索副本不拥有动态结论。不是重新造邮件/流程框架。

## Technical Context
- **Language/Version**: Python >=3.11，保留 Node MCP 薄包装。
- **Primary Dependencies**: 复用现有 Pack、rules/events/project、CLI/MCP；不引入可执行插件或新编排服务。
- **Storage**: 保留每账户 state root；新增本地 `runtime/context/classifications.json` 版本化快照和反馈记录。JSON快照首版适配既有约5k量级；压力不过门再提交独立存储决策，不默默换DB。
- **Testing**: pytest，匿名声明式样例、合成协议夹具、故障回放；不需要真实邮箱开展本地开发。
- **Target Platform / Project Type**: 本地与现有 Linux 宿主，Python库+CLI+MCP。
- **Performance Goals**: 冻结同机同数据基线；新本地分类读取 p95 不高于旧读路径的1.2倍，样本100次并记录分布；快照5k与20k压力测区分目标与探索。
- **Constraints**: 不读时偷偷刷新；不全文出平台；不改默认邮箱只读；无新增部署本轮。
- **Scope**: 三种匿名规则包、二十四业务评测案例候选、动态业务类别及三注意力视图。

## Constitution Check
Phase 0 与设计复查：I 邮箱只读/本地queue不等于IMAP写入；II 有界元数据且无全文；III 分类在TwinBox且下游不透明；IV 原MCP名字/封套兼容；V 密钥不出日志。设计符合，不申请例外。未来实现逐项实测后才算通过交付门。
遵循 [ADR-001](../../docs/decisions/ADR-001-product-boundary-and-semantic-decoupling.md)；本013不改变检索后端。治理依据 [constitution](../../.specify/memory/constitution.md)。

## Project Structure
- 当前接缝：`twinbox_core/{pack,rules,events,project,analyze,pulse,cli,adapter}.py`、`mcp-server.mjs`。
- 拟建：`twinbox_core/{classification_store,evidence_contract,feedback}.py`。
- 拟建测试：`tests/test_semantic_policy.py`、`test_classification_store.py`、`test_evidence_contract.py`、`test_feedback.py`、`test_corrective_handoff.py`、`test_semantic_client_projection.py`。
- 拟建合成夹具：`tests/fixtures/semantic_policy/`、`tests/fixtures/evidence_contract/`；不把真实邮件脱去姓名就直接提交，必须保留合成来源标记。
- 本feature文档：spec/plan/tasks/research/data-model/quickstart/contracts/checklists。三方协议的唯一规范为 [evidence-protocol.md](contracts/evidence-protocol.md)。

## Architecture & Delivery Slices

### P0 — 继承 A–F，先取得可复核基线
旧计划 A–E 逐项映射源码与测试并重跑有界本地用例；F 单独保留运行验证门。任务列表的 completed 不可替代运行证据。详见 [总计划承接表](../../docs/plans/2026-09-18-twinbox-agentos-codex-plan.md)。
必须先复现：审批规则被全局 semantic_band 误归首类；增量抓取不等于分析消费；发布失败与queue-only重建不洗白 freshness。不得趁机覆盖现有 adapter/config/embedding/select 未提交修改。

### P1 — 规则边界与分类结果
- `pack.py` 扩展可验证声明式schema、稳定type/tag ID、display label、明确priority与阈值；引擎只提供通用条件算子。组织实体/业务词仅在Pack。
- 首版每account绑定一个有效Pack（user优先/minimal回退），支持显式选择企业/部门样例；不是自动企业→部门→个人继承。未来多层合并另设冲突语义与权限评审。
- `events.py` 按候选type计算各自语义命中，硬规则与语义证据分别记录；确定性排序用显式priority，再规则ID；优先级相同的冲突不得靠配置顺序悄悄选类。
- 每事项主类0或1，多标签多值；邮件级旧type是兼容摘要，多事项冲突显示mixed/unclassified兼容值，不删除旧字段。原`thread_key`不迁移。
- `project.py` 保留三注意力视图。敏感度仅提示，不能替代ACL；行动责任依赖显式证据与人工确认。

### P2 — 持久投影及覆盖
每账号、来源事项、Pack fingerprint记录派生结果；查询按身份与版本读取，不把短窗pulse当长期档案。原子快照+每账号必要写锁；以revision拒绝丢更新，不声称多文件事务。重算先构建新版本再切active指针；撤权/tombstone先失效，再清理派生缓存。覆盖缺口显式unknown。

### P3 — 证据边界与返回通路
保留现有`build_ingest_envelopes()`兼容输出；新增严格规范化版本，旧的why/action_hint不可充当原文摘录。先契约测试再扩展`adapter.py`，未知业务轴允许、未知协议主版本或安全字段拒绝。
TwinBox→AgentOS传观察而非执行命令；AgentOS→TwinBox传纠正提议/确认/回执。收到反馈先验证来源grant、actor映射和expected_revision；本地审计后接受/冲突/拒绝。管理员单独发布Pack；反馈不能改全局规则/Automation Policy。
拟增加`feedback` CLI子命令和`twinbox_feedback` MCP工具，封套沿用`ok/data/error/recovery_tool`；具体工具参数按合同实现，并同步根SKILL.md。企业传输复用008授权基础，不绕过认证另开口。

## Dependencies & Gates
1. G0 文档/合同审阅与本地旧回归通过后，才能合并新引擎路径；F现场复跑不阻塞合成测试，但阻塞“长程任务已验证”声明。
2. G1 规则只读/隔离/契约负例必须100%通过；已有G1–G6/C1–C10金标原样保留，新增TB13-*，不得重标旧答案。
3. G2 客户端兼容、投影恢复与反馈幂等通过；扩展字段不能被旧客户端误解为自动动作。
4. G3 管理员选择真实Pack与来源授权后才启用；MVP默认minimal和现有读取路径不变。
5. Agent057可与P1/P2并行做mock消费；端到端联调依赖P3。WeKnora014分类筛选依赖P2，基础上传mock不必等它。

## Migration & Rollback
读兼容优先；首次索引重建显式命令，不在普通查询隐式全邮箱扫描。先shadow输出对照，再按账户显式启用。回滚切回旧投影/Pack版本并停新反馈消费，保留历史审计；不以重算撤销已确认数据，不删除旧产物，不批量改IMAP。

## Complexity Tracking
无constitution例外。仅新增本地派生快照、边界校验和反馈记录；不引入新工作流、跨部门继承框架、全业务状态机或全文数据平台。

## Independent delivery and value selection — 2026-09-18

平台先执行[跨场景验证](../../../agent-os-design/docs/plans/2026-09-18-business-value-validation.md)，不等待本feature整体完成；现有证据正确性缺口仅阻塞受影响的试验。分类/检索/反馈可按既有合同独立分片，完整在线接入的投入依据业务基线决定；选中切片不能省略权限、撤权、幂等与恢复门。TwinBox自身维护B02保持独立。本轮只改方案，不改协议schema、不恢复产品实施、不改变活动feature指针。
