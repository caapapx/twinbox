# Data Model — 013（拟建）

## Ownership & Identity
- `SourceScope`: 可信注册的租户+来源账户范围；不是业务部门标签。平台payload不得自报扩权。
- `MailIdentity`: `mail_ref`（账户内稳定内部ID），Message-ID候选、内容冲突标记、一个或多个locator；locator=`account/folder/uidvalidity/uid`。旧thread_key保留为导航。
- `Case`: `case_ref`（opaque稳定ID）、revision、来源mail_refs、关联证据与人工确认；一信多事/多信一事通过关系表意，不复用邮件ID当事项ID。推断自动关联证据不足时保持分离。
- `ClassificationSnapshot`: `(scope, case_ref, pack_fingerprint, classifier_version)`；主类0..1、多标签、多轴、匹配规则、证据basis、observed_at、coverage、source_revision、status。
- `CoverageManifest`: window、枚举来源/案例数、已分析/未覆盖/失败、snapshot_revision、tombstone水位；不是邮件抓取水位的同义词。
- `FeedbackDecision`: `(scope, decision_id)`幂等唯一，payload_digest、actor_ref、case_ref、expected_revision、kind、evidence_refs、状态与拒绝原因。

## Proposed State Files
每account state root下 `runtime/context/classifications.json`（带schema version、active snapshot、coverage）；反馈日志按有限保留滚动。额外checkpoint只有一个权威来源，不与旧待分析消费集合重复定义成功。

## State Transitions
- classification: unknown → candidate → classified/needs_confirmation；新源证据或规则版本使旧结果stale，重算发布后新revision替代；撤权/删除→tombstoned。
- 人工确认是有actor的覆盖层，不被后台重算静默抹除；证据冲突将其标待复核。
- feedback: received → accepted/rejected/conflict；重复同digest返回原结果，复用ID不同digest拒绝。接受`execution_receipt`仅新增外部观察，不自动置业务done。

## Invariants
稳定ID与可变分类分离；Pack fingerprint和classifier版本都影响重算；同source_revision不同payload视为冲突。版本快照原子替换，写锁避免丢更新；跨文件崩溃依靠journal重放和对账，不宣称事务。旧版本读兼容，撤权优先于缓存命中。
