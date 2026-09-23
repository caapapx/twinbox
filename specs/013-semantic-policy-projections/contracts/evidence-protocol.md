# TwinBox ↔ Agent OS Evidence Protocol v1（Proposed）

**唯一规范位置**：本文件及同目录schema/examples。Agent OS057只引用和映射，不维护第二套分类枚举。此协议为拟议新增；当前adapter ingest格式不自动等价于本协议。

## 1. Ownership and Boundary
| 数据 | 权威 | 接收方可做什么 |
|---|---|---|
| 邮件原文/IMAP状态 | 邮件源，经TwinBox读取 | 按授权定位；平台不得持久化全文 |
| 规则、分类、派生轴、queue/pulse | TwinBox | 显示、筛选、提出纠正，不重写业务规则 |
| 协作上下文与线性run | Agent OS既有056/047 | 引用证据、经授权执行、返回回执 |
| 业务完成/验收 | 有证据的业务系统记录或明确人工确认 | 标明依据与观察时间；run成功不自动宣告验收 |
| 检索材料 | WeKnora仅副本 | 返回来源定位，不作为业务状态权威 |

## 2. Forward Observation
见 [observation.schema.json](observation.schema.json) 与 [observation.example.json](observation.example.json)。一条观察对应一个事项的一个revision，可引用多封邮件；同封邮件可用于多个事项。
- `schema_version=1.0`；`observation_id`是投递/观察幂等键，`event_id`是稳定业务事件标识，`case_ref`是事项身份；三者与mail_ref不是同一概念。
- `source.scope_id`/`account_ref`只作选择器，必须与认证绑定匹配；不接受payload的tenant/actor作为授权证据。
- `source_revision`在同scope+case内单调递增；同revision相同payload重放无操作，不同payload冲突隔离。
- `change=upsert|tombstone`；tombstone仅含身份、revision/时间/覆盖，metadata和semantics为null、evidence_refs为空，不继续复制已撤回内容。对于由可信Pack出站策略决定的`reference_only` upsert，`metadata`也必须为null，但仍保留已绑定的mail/evidence引用、semantics和coverage；该形态不复制subject、sender、日期或原文，引用本身不扩大读取权限。
- `metadata.excerpt`必须是经授权的有界原文摘录，不能把why/action_hint包装为原文。推断和理由另在typed semantics/evidence_basis表达；不能用无限自由attributes传任意嵌套对象。没有Pack匹配策略、新出现的轴值或不合法策略一律降为`reference_only`；只有Pack显式列出的轴/值可选择`allow`、`truncate_excerpt`或`omit_excerpt`，多条匹配规则取更严格的操作。
- `semantics`含主类、标签map、轴map、规则版本信息；类别ID不在平台硬编码。业务未知类别可保留/显示raw label；保留键`acl/permissions/roles/grants/security`不得用业务标签覆盖。
- `evidence_refs`仅引用已验证输入中的mail_ref与片段定位，最多32项；引用本身不授予访问权。basis=explicit/inferred/insufficient为证据来源类型，不是执行授权或统计置信度。
- `coverage.state=complete|partial|unknown|stale`是该声明窗口和案例的覆盖，不是声称整个企业邮箱完备。
- 限制（拟议v1）：单条UTF-8序列化<=32KiB；subject<=256、sender<=254、excerpt<=512个Unicode字符；业务tags/axes各<=16键；tag每键<=8值、值<=96字符；总批次<=100条。超限不静默截证据：出站明确截断metadata并记录标记，接收方拒绝不合规输入。
- schema约束之外仍需来源allowlist、可信字段构造和内容最小化；仅靠字段名/正则不能保证任意字符串不夹带秘密。原文摘录须经过批准的出站裁剪/脱敏策略；缺策略不外发。

## 3. Pagination and Compatibility
拉取cursor为opaque版本化token，绑定scope、序列高水位、filter fingerprint与过期时间；不要用hash词典序混ISO时间。并发新增时按冻结高水位分页，下一轮继续新水位；过期返回`cursor_expired`及显式重建指引，不默默返回空集。tombstone与upsert共用顺序序列。
现有`build_ingest_envelopes`保留兼容层；legacy输入必须由可信adapter补齐scope和校验后的字段，无法补齐则拒绝，不伪造证据。主版本未知拒绝；minor新增业务字段仅按协商capability接收，安全含义变化须升级版本，不静默忽略。

## 4. Reverse Feedback
见 [feedback.schema.json](feedback.schema.json) 与 [feedback.example.json](feedback.example.json)。
必填：schema_version、decision_id、scope_id、case_ref、expected_revision、actor_ref、kind、evidence_refs、decision。actor_ref由认证delegation验证，不信任客户端任填。
- correction_proposal：建议修改主类/标签或责任目标；仅进入提议层。TwinBox经授权确认后才生成新的派生revision；不能远程运行任意patch。
- human_confirmation：记录明确业务确认；需来源确认权限。queue done如需同步必须明确目标与既有本地queue策略，不写IMAP。
- execution_receipt：记录run_ref、结果、发生时间与证据；仅新增外部观察，不自动变“已验收/已归档”。
`decision`为严格kind对应对象；未经匹配的字段拒绝，不能用它发布Pack、ACL或Automation Policy。

## 5. Reply, Retry and Conflict
TwinBox工具封套保持`ok/data/error/recovery_tool`。业务结果`status=accepted|conflict|rejected`，伴source_revision和有界reason_code；传输未完成仅在发送方记pending/retry_wait，不伪造accepted。
同(scope, decision_id)同payload_digest返回原结果；同ID不同digest拒绝`idempotency_conflict`。expected_revision过旧返回`revision_conflict`和当前revision，但不向无权actor返回内容。重试必须复用同decision_id；冲突需重新读取并由人或明确策略重新决定，不能无限自动改expected_revision重试。
授权撤回立即阻断读取、执行和反馈。平台outbox先查有效grant；拒绝类错误停止重试，超时/暂时服务不可用有界指数退避（最多5次，之后needs_attention），无凭据/正文日志。

## 6. Security and Tests
双端同时校验schema、总大小、来源绑定、case归属、字段allowlist与证据引用；nested body/MIME/附件、role提升、陌生source、未知安全语义、重放和错误revision均为负例。source grant与membership/execution authority分别检查。
撤权消息处理之前仍须依靠实时权限绑定/失效标记保证不能读旧缓存；仅异步tombstone不是完整撤权方案。事件回放默认只重建投影，不自动启动run或发送消息。
