# 014 WeKnora 现场能力与授权核验矩阵

**状态**：`partial`（ADR-004 与 retention 已记录；现场 grant 的 `account_ref=shared-aion`，`mail_refs` 有一条 opaque locator；正文未同步，运行时开关仍关）
**用途**：为 T008/T010 收集可审计、脱敏的现场证据。此文件不是 WeKnora API 的事实来源；实际端点、字段和状态必须以目标环境 Swagger 为准。

## 1. 门禁结论

在下表全部必需项取得证据前，014 只能使用本地 fake-provider，`weknora.enabled` 必须保持关闭；不得读取真实邮件正文、创建真实 KB、写入真实知识或执行现场回放。

| 门禁 | 当前状态 | 需要的最小证据 | 证据落点（待填写） |
| --- | --- | --- | --- |
| ADR-004 接受 | `recorded` | 负责人、日期、接受记录；明确 sidecar 默认路径与回退策略 | [ADR-004](../../docs/decisions/ADR-004-optional-weknora-retrieval-proposed.md) 2026-09-22 Accepted；运行时 `adr_004_accepted` 仍为 false，接受记录不打开开关 |
| 专用知识库 | `done` | 租户/账户隔离说明、KB 标识（脱敏）、所有者 | 租户 10001；邮件空壳库 `邮件 9c2d23ae…`、团队会议库 `团队会议 63907aa3…`，同 embedding，不混分；所有者 admin |
| 独立最小写权限 key | `done` | key 仅存在于受控凭据存储；只记录 presence，不记录值 | tenant key（meetmail profile，scope 仅上两库，`retrieve/chat/ingest/message_history`，已去 `manage_kbs`）；值仅 weknora-ops gitignored creds + 251 agent env，presence 已验证 |
| API 能力 | `verified` | 目标环境 Swagger 中的创建、查询、更新、解析状态、检索、删除能力矩阵 | 2026-09-21 实测：建库/列表/`manual` 创建/带全文 PUT 发布/单篇 parse 查询/hybrid-search；单篇 `DELETE /knowledge/:id` 合成探测文档 200+`task_id` 异步 pending。`manual` 默认 draft、`publish` 须带全文（`published` 400）；管理面 Bearer、业务面 X-API-Key。真 provider + CLI `status|sync|revoke` 已接线（三重门，测试零真实网络）；门未开故默认关闭 |
| 检索前授权隔离 | `partial` | 证明 KB/文档级过滤可在检索前生效；不能以结果后过滤替代 | scoped key 只能列出授权的 2 个库（KB 级隔离已验证）；账号 grant 已落地且 `mail_refs` 为空，文档级过滤要等列入一条摘录后再验 |
| 幂等与超时对账 | `partial` | source key 查询、创建超时后的 reconcile、映射丢失恢复证据 | 先按 title/channel 查再 PUT，会议纪要 4 篇零重复已验证；真超时 reconcile/映射丢失恢复仍是 fake 合同，未做真演练 |
| 保留与删除 | `recorded` | retention、撤权先隐藏后删除、失败重试和审计要求 | [retention.md](retention.md)；单篇 DELETE 已用合成探测文档核验为异步 pending；关开关不自动删副本 |
| 脱敏/有界摘录 | `defined（待真样本）` | 明确允许字段、正文上限（当前合同为 512 字符/32 KiB payload） | 上限与 allowlist 见合同；真 mail excerpt 样本待公共邮箱 grant 落地后 |
| 30 条人工金标 | `mock-first accepted` | 匿名 query、旧基线冻结结果、候选冻结结果、owner 签字 | grill 2026-09-21 Q4：mock 先行，真值等落盘后冻结；T009 mock 可做，真金标待定。mock 基线已跑：`tests/fixtures/weknora/mock-30.json` + 新旧 runner 结果 → `docs/runtime/weknora-retrieval-mock-20260921.json`（`fixture_not_human_gold`，三组 recall 1.0/1.0，不作启用结论） |
| 回退验收 | `pending` | 关闭开关后旧 sidecar 正常、权限不扩大、证据在 `docs/runtime/` | 待小样本阶段演练 |

## 2. 能力矩阵（只填脱敏结果）

| 逻辑能力 | 现场是否支持 | 证据类型 | 备注 |
| --- | --- | --- | --- |
| `lookup_by_source_key` | `mapped（fake transport）` | 本地 HTTP 映射测试 | 按 title + `channel=twinbox` 列表对账；0 条 `missing`，>1 条 `conflict`；不把 URL/key 写入本文件 |
| `create_excerpt` | `mapped（fake transport）` | 本地 HTTP 映射测试 | `POST .../knowledge/manual` 后带全文 `PUT .../knowledge/manual/:id` + `status=publish`；`published` 现场会 400 |
| `update_excerpt` | `mapped（fake transport）` | 本地 HTTP 映射测试 | 同一 PUT 发布路径；冲突保护仍靠本地 hash/journal，不假设服务端 unique key |
| `get_parse_status` | `mapped（fake transport）` | 本地 HTTP 映射测试 | `GET /knowledge/:id`；`draft/pending/processing/finalizing` → pending；`completed` → ready；其它 → unknown |
| `search` | `mapped（fake transport；文档级 ACL 未现场验）` | 本地 HTTP 映射测试 | 单 KB `hybrid-search`；隔离靠 KB 路径 + scoped key；文档级 grant 过滤待公共邮箱落地 |
| `delete_excerpt` | `mapped（fake transport；现场探测已核验）` | 合成探测文档 DELETE，非邮件 | `DELETE /knowledge/:id` 返回 200 + `task_id`（异步），随后列表为空；立即 GET 可能仍 200。适配器将带 `task_id` 的 200 记为 `pending`，404 为 `absent`。探测标题 `__014_delete_probe__` 已清 |

## 3. 核验规则

- 只能使用 `weknora-ops` skill 的受控凭据与目标环境；不得把 API key、JWT、密码、真实 URL、邮箱地址、Message-ID、路径或正文写入 git、日志或此文件。
- 结构化邮件知识使用 `manual` ingest；除非后续 TwinBox overlay 明确批准，不上传原始 MIME/eml、附件或全量正文。
- 所有请求带 `X-API-Key` 与 `X-Request-ID`（认证端点除外）；每次写入后必须检查 parse status。
- 同一业务键先查映射/按 title/channel 对账，再决定 `PUT` 更新；禁止未经对账的重复 `POST`。
- 不同 embedding 模型的 KB 不做跨 KB 混合检索；检索 score 必须保留 origin。
- 任何授权隔离、删除语义或保留策略无法证明时，保持关闭，不以“结果后过滤”补救。

## 5. grill 决议记录（2026-09-21，owner 确认）

1. ADR-004 → Accepted，记录在 `docs/decisions/ADR-004-optional-weknora-retrieval-proposed.md`。运行时开关仍关。
2. 首批 grant → 一个公共邮箱 scope。现场状态 `account_ref=shared-aion`，`mail_refs` 含一条已有本地索引的 opaque locator（`folder#uid`）。正文未复制到 KB，邮箱地址不写入本文件。
3. retention → [retention.md](retention.md)。撤权先隐藏后删除，失败保持不可见并可重试；不删 IMAP。
4. 金标顺序 → mock 先行，真值等落盘后冻结。
5. meetmail key → 已去 `manage_kbs`（2026-09-21 key 轮换验证），转纯 ingest。

## 6. 现场核验输出要求

核验完成后只追加以下脱敏信息：

1. 核验日期、环境别名和 skill 版本；
2. 逻辑能力支持矩阵及 Swagger 版本/摘要；
3. 专用 KB/key 的 presence 与授权范围（不含值）；
4. retention/delete、检索前 ACL、解析状态、幂等对账结论；
5. 失败项、回滚方式和批准人；
6. 指向 `docs/runtime/` 的证据文件名。

在上述信息齐全且 ADR 被接受前，不得把 T008 或 T010 标记为完成。
