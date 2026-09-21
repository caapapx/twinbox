# Data Model — 014（本地 fake-provider 接缝；现场仍未接入）

## SourceIdentity
共享013 mail_ref与scope；内部canonical key至少包含tenant/account namespace。Message-ID规范化只trim外层空白/合法尖括号，不随意lower-case全部值。相同scope+Message-ID也须核对稳定内容指纹；冲突生成独立内部身份并标记，禁止覆盖既有材料。缺Message-ID保留本地持久UUID与locator映射，跨文件夹疑似重复只提议合并，不保证无证据自动去重。
UIDVALIDITY变化使旧locator失效但不删除稳定mail_ref。不同scope绝不自动合并。

## MappingEntry
`(scope_id, mail_ref)` → `account_ref, thread_key, knowledge_ref, stable_title_key, excerpt_hash, payload_revision, writer_id, visibility, sync_state, parse_state, attempt_id, pending_operation, last_error_code, updated_at`。
`writer_id` 仅用于本地 state-root 的显式单写者隔离：已有声明写者时，第二个不同写者必须以 `writer_conflict` 隔离，不能静默接管。`visibility` 为 `visible` 或 `hidden`；hidden 的映射即使远端删除尚未完成也不得进入查询 allowlist。新增/更新内容 hash 只基于批准出站字段。稳定 title 为带 scope/account 的非明文身份键，subject 独立元数据，避免标题变化导致重复。哈希不是授权或脱敏保证。

## Sync Journal
prepared → lookup → uploading → uploaded → parsing → searchable；失败分retryable/permanent/quarantined。
POST timeout → uncertain → reconcile；查明存在才能写 mapping，查明未创建才新 attempt。映射丢失时也先用稳定键 lookup 与 payload hash 对账；无法查明保持 quarantined，不凭超时重新创建。
delete/revoke: hidden 立即生效 → delete_pending → deleted；删除失败、pending 或 timeout 均不恢复可见。按批准策略处理索引保留，不反向删除 IMAP。

## SearchHit
`knowledge_ref, mail_ref, thread_key, excerpt, retrieval_backend, score_origin, classification_coverage, live_status`。
`live_status`只来自当前有效TwinBox观察；无有效窗口时null，不能取KB描述拼出“当前状态”。不同score_origin不直接算术比较；首版单后端优先+明确fallback，不做跨KB混排。
