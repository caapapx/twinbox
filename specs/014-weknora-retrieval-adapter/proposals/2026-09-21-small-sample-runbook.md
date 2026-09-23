# T010 小样本验收 runbook（准备稿，不执行）

**日期**：2026-09-21 | **性质**：准备稿。所有步骤缺前置即停，不降级执行。
**前置**（缺一即停）：一条已批准摘录的 opaque `mail_ref` 已写入现场 source grant。账号 grant、ADR-004 接受记录、retention 策略已经在位；`weknora.enabled` 与 `adr_004_accepted` 仍须在演练前显式打开，缺一即停。

## 0. 门禁确认（只读）

```bash
twinbox weknora status --account-id <公共邮箱 account_ref>
```

期望：`enabled=true`、`adr_004_accepted=true`（正式记录后）、`live_provider_available=false`（开关含义不变）。
任一不满足即停，不进入第 1 步。

## 1. 单条批准摘录同步

- 用已批准的 1 条 mail excerpt（来自公共邮箱授权范围，非全量回填），走：
  `twinbox weknora sync --account-id <…> --payload-json '<source>'`
- 期望：`created` + `knowledge_ref` + `parse_state=pending`；`uncertain` 则按 journal 对账后只 lookup 不重建。

## 2. 解析等待（只读轮询）

```bash
WEKNORA_PROFILE=meetmail wk.sh knowledge-status <knowledge_id>
```

- 到 `parse_status=completed` 才算就绪；`pending/processing/finalizing/draft` 一律不等同就绪；`failed` 读现场 `error_message` 后停（`knowledge-status` 不打印正文）。
- 邮件库短 id `9c2d23ae…`，全 id 用 `WEKNORA_PROFILE=meetmail wk.sh kb-list` 现场解析，不写死。

## 3. 检索对照（只读）

同一 query 分两条链路，score 不混排，只记各自结论与 origin：

```bash
# 旧 sidecar（TwinBox 本地，不读新 KB）
twinbox thread "<query>" --json

# 新 hybrid-search（meetmail scoped key）
WEKNORA_PROFILE=meetmail WEKNORA_MATCH_COUNT=5 wk.sh search <kb_id> "<query>"
```

记 Recall@5 / 延迟 / 成本。缺前置（公共邮箱 grant、ADR 正式记录）即停，不降级拿真实邮件凑样本。

## 4. 撤权演练

```bash
twinbox weknora revoke --account-id <公共邮箱 account_ref> --mail-ref <opaque-mail-ref>
```

- 先隐藏后删除：本地 mapping `visibility=hidden`，再 `DELETE /knowledge/:id`。现场该 DELETE 为异步（200+`task_id` → 适配器 `pending` → mapping `delete_pending`）；再调一次 `revoke` 直到 `deleted`/`absent`。
- grant 关闭后仍可 revoke（新 `sync` 会被拒）；`--mail-ref` 必须落在原 grant 的 mail_refs 内。
- 三重门未开（`enabled`/`adr_004_accepted`/凭据缺一）时不发起网络，只做本地隐藏，mapping 停在 `delete_pending`。
- 演练通过标准：关闭 grant 后 `sync` 拒绝；已建副本检索不可见；`revoke` 返回 `deleted` 或可重试的 `delete_pending`；不宣称 T010 完成。

## 落地模板（占位符，owner 指定公共邮箱前不要填真实账号）

`config/source-grant.json`：

```json
{
  "schema_version": "1.0",
  "scope_id": "<scope>",
  "account_ref": "<公共邮箱 account_ref>",
  "mail_refs": ["<opaque-mail-ref>"],
  "evidence_refs": [],
  "enabled": true
}
```

单条 sync payload（`original_excerpt` ≤512 字；禁止 MIME/附件/推断字段）：

```json
{
  "scope_id": "<scope>",
  "account_ref": "<公共邮箱 account_ref>",
  "mail_ref": "<opaque-mail-ref>",
  "original_excerpt": "<已批准摘录>",
  "subject": "<bounded>",
  "sender": "<bounded>",
  "date": "<bounded>",
  "folder": "<bounded>",
  "thread_key": "<bounded>"
}
```

## 5. 关闭与证据

- 关 `weknora.enabled`，确认旧 sidecar 检索正常（回退验收）。
- 证据落 `docs/runtime/`（gitignore，不入仓）：对账记录、parse 截图脱敏版、sidecar/新链路对照表、批准人。
- 以上齐全且 ADR 正式记录在位，才谈 T008/T010 勾选；mock 结论永不作为启用依据。
