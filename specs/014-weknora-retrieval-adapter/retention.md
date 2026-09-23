# 014 摘录副本保留与撤权

**状态**：Accepted（owner grill 2026-09-21 Q3；2026-09-22 写成策略）
**范围**：WeKnora 里的有界摘录副本。源邮件留在 IMAP。

## 保留

- 副本只含合同允许字段：`channel=twinbox`、opaque scope/mail_ref、稳定 title、有界 subject/sender/date/folder/thread_key、原文摘录不超过 512 字，整包不超过 32 KiB。
- 分类、queue、pulse、LLM 推断、MIME、附件不进 KB。
- 未写入 source grant `mail_refs` 的信件不得同步。
- 关闭 `weknora.enabled` 只停新的同步和检索路径，不自动删除已有副本。

## 撤权

1. 本地 mapping 立刻 `visibility=hidden`。此后 sync 与 search 都看不到它。
2. 再调用 `DELETE /knowledge/:id`。现场该调用返回 200 和 `task_id` 时记为 `pending`，mapping 停在 `delete_pending`。
3. 超时、失败或仍 pending 时保持隐藏，并可用同一次 `revoke` 重试。失败不得把可见性改回去。
4. 收到 `deleted` 或 `absent` 后，mapping 记为 `deleted`。
5. grant 关掉之后仍允许对原 `mail_refs` 做撤权。新的 sync 会被拒绝。

## 审计

本地 journal 只记时间、scope、opaque mail_ref、attempt、操作名和有界错误码。不记正文、密钥或供应商响应体。索引删除不触发 IMAP 删除。
