# Retrieval Adapter Contract（Proposed）

## Provider port（能力而非臆造现场HTTP路径）
- `lookup_by_source_key(scope, stable_key)` → zero/one/conflict，必须在授权KB内精确确认。
- `create_excerpt(scope, stable_key, payload, attempt_id)` → knowledge_ref / uncertain。
- `update_excerpt(scope, knowledge_ref, expected_hash, payload)` → accepted/conflict/failed。
- `get_parse_status(scope, knowledge_ref)` → pending/ready/failed/unknown。
- `search(scope, query, authorized_filter, classification_filter?, limit, deadline)` → bounded hits + coverage。
- `delete_excerpt(scope, knowledge_ref)` → deleted/absent/pending/failed。
以上为适配器逻辑接口；实际REST URL、字段/状态和幂等支持必须通过现场版本及swagger核验，再固化mock响应。不能把ops脚本或AgentOS旧weknora.py当产品接口事实。

## Ingest allowlist
`channel=twinbox`、opaque source scope/mail_ref、稳定title key、subject/from/date、folder/thread_key定位、bounded original excerpt（<=512字符，且整个payload<=32KiB）。身份与修订hash可存在本地映射，远端仅必要identity字段。
禁止queue_tags、projection、业务type/axes/tags、Pack内容、why/action_hint、LLM输出、full body、eml、MIME、附件、向量或密钥。运营“归档”只表示建立检索副本，不移动或标记邮箱。
源原文excerpt必须独立于旧ingest的推断excerpt构造，按授权过滤和字符边界截断；无授权原文则只传允许的元数据并标无excerpt，不以推断补造原文。

## Identity / Mapping
依照 [data-model.md](../data-model.md)。Message-ID只在scope内作候选；同候选不同稳定内容不合并；缺ID生成持久内部身份。相同内容但不同来源不自动当同业务事项。title稳定键不包含变化分类，mapping按scope隔离。
映射缺失先lookup再create，超时保留attempt journal并reconcile。服务端没有唯一键时，只允许专用单写者；无法对账则隔离，不能承诺严格exactly-once。

## Retrieval / Authorization
1. 验证principal到source scope授权，构造检索前约束；服务端必须支持匹配的KB隔离或文档级grant过滤。
2. 分类筛选由013分类索引生成 `knowledge_refs` allowlist 或在已授权结果集做后过滤；ACL不能后过滤替代。补取最多3页且受总deadline限制；不足则partial，不伪造无结果。
3. `knowledge_ref`→本地mail_ref/thread_key映射，再查013语义与有效pulse状态；没有当前状态则`live_status:null`。
4. 不同检索源score带origin；第一版只选一个后端或显式fallback，不混原始分数。
5. 超时/解析失败/HTTP错误统一有界diagnostics，不透传响应全文；回退sidecar沿用原grant。

## Retention / Enablement
无真实KB写入直到ADR、授权scope、独立写key、API能力与保留/删除策略获确认。撤权先停止可见及查询，再删除；不能保证检索前隔离则全停该KB入口。索引材料删除不触发源邮件删除。
本地配置使用`weknora.enabled=false`等拟定配置，由实施时合并现有schema；不在计划放真实URL/key，不执行开户/建KB/批量回填。
