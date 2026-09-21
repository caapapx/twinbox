# 014 落盘链路实施方案（W3）：真 provider 接线

**日期**：2026-09-21 | **性质**：proposal，只出方案，不执行、不动现场
**前置**：`plan.md`（W0–W2 fake-only）、`contracts/retrieval-adapter.md`（Proposed）、`research.md`（全门 pending）
**不做**：不读真实邮件、不批量回填、不改默认检索拓扑、不勾选 `tasks.md` 任何框（含 T008–T010）。

## 1. 已验证的现场事实（2026-09-21 实测；当晚收权后校正）

- 专用邮件 KB 已建：`邮件`（与 团队会议 / 流程 / 制度库同 embedding `builtin-embedding-default`，跨库不混分），当前为空壳，不灌真实邮件。
- 写权限 key：`meetmail` profile（tenant key **id 12**，替换已删的 id 11），仅绑 团队会议 + 邮件，能力 `retrieve/chat/ingest/message_history`（**无** `manage_kbs` / `full_access`）；值只在 `weknora-ops/scripts/.credentials`（gitignore），251 通信智能体 `weknora.env` 另有只读用法。
- 会议纪要 4 篇已进 团队会议库并可检索：`manual` + `channel=agentos-meetings` + 稳定 title（文件名），`parse=completed`。
- provider：`twinbox_core/weknora_http.py` + CLI `status|sync|revoke` 已接线；三重门默认关闭。单篇删除已用合成探测文档核验：`DELETE /knowledge/:id` → 200 + `task_id`（异步 pending），随后列表为空。

## 2. 本轮实测校正的接口行为（进 factory 设计）

1. 业务面鉴权是 `X-API-Key`；`/auth/login` 返回的 Bearer 只用于租户管理面（建 key、列 key），不能混用。
2. `manual` 创建默认 `parse=draft` 不解析；发布必须带全文 `PUT /knowledge/manual/:id` + `status=publish`（`published` 会 400）。
3. 单篇状态走 `GET /knowledge/:id`，不是 `GET /knowledge-bases/:kb/knowledge/:id`（后者 404）。
4. 幂等靠「先按 title/channel 列表，再 PUT」；禁止盲 POST（本轮 4 篇零重复即用此路径）。
5. 带 `manage_kbs` 的 scope key 也能建库：已轮换为无 `manage_kbs` 的纯 ingest key（id 12）。

## 3. 接线设计（代码改动清单，已落地、默认关闭）

- 新增 `twinbox_core/weknora_http.py`：实现 `WeKnoraProvider` 六方法到 REST 的映射（lookup/create/update/parse/search/delete），超时有界、错误只记有界错误码、不透传响应正文、不记日志正文。**已实现并测试（2026-09-21，`tests/test_weknora_http.py`，零真实网络）。** 单篇 `DELETE /knowledge/:id` 已用合成探测文档核验（200+`task_id` 记 pending）；factory 默认该路径，可用 `WEKNORA_DELETE_PATH` 覆盖。
- 凭据只从环境变量（沿用 skill 约定 `WEKNORA_BASE_URL` / `WEKNORA_API_KEY`，值走受控凭据存储）；KB 标识只进本地运行态配置/state，不进 git、不进合同。
- factory 三重门（缺一即拒绝真实调用，回退 fake/sidecar）：`weknora.enabled=true` + ADR-004 accepted 标记 + 按 scope/account 的 source grant 存在。默认全关。`twinbox weknora revoke --mail-ref` 在 grant 关闭后仍可本地隐藏；门未开不发起网络。
- 小样本验收（T010 形状，证据进 `docs/runtime/`）：批准摘录 N 条 → 对账 → parse watch → sidecar 对照 → 撤权隐藏→删除演练 → 关闭开关后旧链路可用。三十条人工金标（T009）仍是前置比较基线，mock 可先行，真值等落盘后冻结。不得勾选 T008/T010。

## 4. 待拍板（owner 门，方案不替代）—— 2026-09-21 grill 决议已记入 `research.md` §5

1. ADR-004 接受 → **已接受（owner 口头，正式记录待补）**。
2. 首批 scope/account 的 source grant 与专用 KB 授权范围确认 → **范围已定（一个公共邮箱），具体邮箱待指定**。
3. retention/撤权删除策略批准 → **语义已同意，正式策略文档待批**。
4. 30 条匿名人工金标的 owner 签字与冻结（T009）→ **mock 先行，真值等落盘后冻结**。
5. meetmail key 是否去掉 `manage_kbs` 转纯 ingest → **已执行并验证**。

`weknora.enabled` 保持关闭；`research.md` 门禁表逐项填证据后再谈 T008/T010。
