# Implementation Plan: WeKnora 可选检索适配器

**Git checkout**: `master`（未切分支） | **Date**: 2026-09-18 | **Spec**: [spec.md](spec.md)  
**Feature selector**: `SPECIFY_FEATURE_DIRECTORY=specs/014-weknora-retrieval-adapter`  
**Status**: 本地 W0–W2 已实现并经 fake-provider 验证（2026-09-20）；真实 WeKnora 对接、KB写入、人工金标评测与发布仍为独立 gate，未开始。

## Summary
在现有 sidecar 检索外新增默认关闭的薄适配器。坚持专用KB、原文有界摘录、KB零业务派生字段、来源隔离、幂等对账和可回退。长期分类索引来自013，不依赖短期pulse代替长期档案。

## Technical Context
- **Language/Version**: Python >=3.11；复用现有HTTP与配置习惯，不引入重型检索框架。
- **Storage**: 每账户 `runtime/context/weknora-sync.json` 与有界同步journal；锁+原子替换，不声称跨进程/跨服务事务。
- **Dependencies**: `twinbox_core/{config,embeddings,select,adapter,imap_fetch}.py`；新增`weknora.py`，共享013身份/权限合同。
- **Testing / Target**: pytest本地mock、离线查询集；现场只在明确授权后用专用KB进行有限只读检索与已批准索引写入。
- **Performance Goals**: 本地mock配置注入deadline；初始远程检索总预算2秒、单次重试受总预算约束，不把上传/解析串进用户读请求。试点记录p50/p95与失败率再决定是否调整。
- **Constraints**: 新服务错误不阻塞邮件分析；不能用更宽权限fallback；不移除旧sidecar。
- **Scale/Scope**: 单专用KB、三十条冻结查询；跨KB与自动全量历史回填默认不做。

## Constitution Check
Phase 0/1设计满足全文边界、默认只读邮箱、分类留TwinBox、工具兼容与凭据隔离。外部摘录副本只在自托管、专用最小权限且获批范围内开启；不改变自托管embedding/LLM边界。
现行 [ADR-003](../../docs/decisions/ADR-003-retrieval-spine-and-external-services.md) 仍有效；[拟议ADR-004](../../docs/decisions/ADR-004-optional-weknora-retrieval-proposed.md) 未接受前，仅可开发禁用路径与mock，不切默认检索拓扑。

## Project Structure
- 已新增（本地 mock）：`twinbox_core/weknora.py`（capability port、mapping、reconcile、search 薄适配）。
- 已新增（默认关闭）：`twinbox_core/weknora_http.py` HTTP factory；CLI `weknora status|sync|revoke`；三重门未开不发起网络。单篇 `DELETE /knowledge/:id` 已核验为异步 pending；factory 默认该路径。
- 已修改（本地 mock）：`config.py` 默认关闭配置（`adr_004_accepted=false`）、`cli.py` 显式同步/诊断/撤权、`select.py` 的受 grant 约束 sidecar 回退；复用既有 embedding sidecar，不改 `embeddings.py`。`adapter.py`只能复用身份，不能用其推断excerpt直接入库。
- 已新增（本地 mock）：`tests/test_weknora_sync.py`、`test_weknora_search.py`、`test_weknora_security.py`、`test_weknora_http.py`；T009 mock harness 已有，真金标未冻结。
- 文档与合同：[contracts/retrieval-adapter.md](contracts/retrieval-adapter.md)、研究、数据模型、任务及quickstart。

## Delivery Slices
1. **W0 本地mock合同**：依据旧草案制定能力接口，不臆造现场REST路径；身份、状态、ACL能力差异用明确失败表示。
2. **W1 有界同步与幂等**：从授权缓存解码原文提取excerpt；先持久记录intent，再按稳定键查存在性，必要时创建/更新；POST timeout进入unknown/reconcile，绝不直接再次POST。
3. **W2 查询接入**：先约束KB/租户/grant；命中 `knowledge_ref` 解析本地映射；join013分类，再join pulse当前状态。没有授权过滤能力则拒绝新路径。业务分类可预过滤或在授权结果上后过滤，但需有界补取和覆盖标记。
4. **W3 验证再启用**：现场swagger/version/capabilities、专用key/KB、保留策略与解析状态通过gate后，才做授权小样本；三十查询过门再按account启用。

### Local implementation status — 2026-09-21
W0–W2 仍只在 fake-provider 合同下验证。W3 接线（`HttpWeKnoraProvider` + 三重门 factory + `weknora revoke`）已落地且测试零真实网络；`weknora.enabled` / `adr_004_accepted` 默认关闭，sidecar 主干不变。ADR-004 接受记录与 retention 策略已写入；现场 grant 的 `mail_refs` 仍空，不勾 T008–T010。

## Identity, Search & Failure Policy
Message-ID不是全局唯一，也不是ACL。规范身份算法与冲突规则见合同；locator包含account/folder/UIDVALIDITY/UID，原thread_key只作导航。
上传状态与检索状态分开，不等待parse完成；持续失败暴露数量与原因。映射丢失从title稳定键+必要元数据重建，不扫描/读取无权文档。服务端不支持唯一键时客户端锁和对账仍不能承诺跨独立写者exactly-once：专用KB只允许本写者，发现多写者或无法确认创建结果则隔离待处理。
API 401/403/解析失败/超时分别诊断；同授权sidecar可继续，不能放宽来源。只记录有界错误码，HTTP响应正文不得原样入日志。

## Gates & Rollback
- **L0** 拟议ADR获接受、管理员批准专用KB/最小key、现场接口能力核对、来源授权/保留策略确认：未过门无真实入库。
- **L1** 013分类索引覆盖是分类检索前提；基础无分类检索可以独立验证，但不得称全历史业务分类已可用。
- **L2** 三十查询固定人工标注，Recall@5总体及各组不低于sidecar；关键词单列，零越权。二十四业务案例不能代替这项检索实验。
- **L3** 删除/撤权先从路由与查询可见范围撤除，再异步清理；清理失败继续不可见并报警。若KB不能实现需要的隔离则停该KB查询。
- **Rollback** 按账户关闭WeKnora开关，保留sidecar；暂停上传不等于清除既有数据，按批准保留策略另行执行带审计的删除。回滚演练必须验证原邮件分析可用。

## Complexity Tracking
无新向量存储/服务编排。拒绝把queue_tags、业务标签、LLM结论复制进KB；拒绝因WeKnora引入第二分类真相源。新增运维工作必须计入ROI。

## Independent delivery and value selection — 2026-09-18

平台先执行[跨场景验证](../../../agent-os-design/docs/plans/2026-09-18-business-value-validation.md)，不等待本feature整体完成；现有证据正确性缺口仅阻塞受影响的试验。分类/检索/反馈可按既有合同独立分片，完整在线接入的投入依据业务基线决定；选中切片不能省略权限、撤权、幂等与恢复门。TwinBox自身维护B02保持独立。本轮只改方案，不改协议schema、不恢复产品实施、不改变活动feature指针。
