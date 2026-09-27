# 014 有界评测协议（不执行同步）

**日期**：2026-09-24  
**性质**：评测边界。本文件不授权开闸、不改 [config/schedules.yaml](../../../config/schedules.yaml)、不批量回填。演练通过不等于 T008/T009/T010 完成。

## 样本上限

- 一次评测最多使用已有候选，不新抽邮件窗口。
- 公共 `shared-aion`：已有开发集 12 条。
- 个人近窗：注意力 5 条。
- 2025 Q3：每个槽位最多 3 条代表（周报、发布、联调、运维服务报告、部署）。
- 写入知识库的条数另设硬上限：首轮仍是 N=1；扩大前必须单独批准新的 `mail_refs`。
- 已见样本不能当盲测 holdout。

## 摘录字段

允许进入外部副本的只有：

- opaque `mail_ref`（`folder#uid`）
- `scope_id` / `account_ref`
- 有界 `original_excerpt`，最多 512 字符
- 必要来源元数据：主题、发件人、日期、文件夹

不进入副本：MIME、附件、全量正文、待办状态、LLM 结论、`waiting_on`、queue/pulse。
可选进入副本（版本化白名单投影，非第二真相源）：`project_ref`、`event_slot`、`source_kind`、`date`、`classification_coverage`。分类变化更新同一文档标签，不拆多库。

## 查询分组

固定对照分三组，每组在人工金标冻结前只记协议、不报召回结论：

1. 关键词：项目名、版本号、槽位词（发布、联调、部署）。
2. 语义：用问题描述找历史材料，不要求命中原主题词。
3. 分类：按 Twinbox 已有槽位过滤；分类变化不回写知识库标签。

对照臂：Twinbox sidecar、可选的知识库检索、关开关后的 sidecar。知识库失败或超时必须回退 sidecar，并标明降级。

## 关闭与撤权

1. 只对 grant 里的 `mail_ref` 调用 `twinbox weknora sync`。
2. 等到解析完成再检索；未完成不算可检索。
3. 检索只打邮件库，不把会议库并入同一次查询。
4. 结束时对本次 `mail_ref` 执行 revoke：先隐藏，再删除，失败保持不可见。
5. 关闭 `weknora.enabled` 与 `adr_004_accepted`。
6. 确认 sidecar 仍能返回同一 `mail_ref`。
7. 证据只写 `docs/runtime/`，不写正文、密钥或邮箱地址。

## 本轮停止

- 不把写入挂进 `daytime-sync` 或 `nightly-full`。
- 不打开运行开关作为默认状态。
- 不勾 T008、T009、T010、BV 或 ROI。
- 下一轮才讨论：grant 内增量 sync、`thread` 可选调用 `search_excerpts`、失败回退 sidecar。那一轮仍默认关开关。
- 分级目标、阻塞和日期见 [联调路线](2026-09-24-weknora-sync-roadmap.md)。那份路线不放宽本文件的样本上限和撤权规则。
