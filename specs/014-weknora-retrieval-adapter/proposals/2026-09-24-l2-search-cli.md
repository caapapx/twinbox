# L2 Twinbox WeKnora 检索子命令（proposal）

**日期**：2026-09-24  
**性质**：设计稿。不改 `cli.py`，不开开关，不调现场 sync/search。实现需另一次授权，且不早于 L1 有内容证据落盘。  
**依赖**：[联调路线](2026-09-24-weknora-sync-roadmap.md) L2；[有界评测](2026-09-24-bounded-eval.md)；[审阅图](2026-09-24-review-diagrams.md)。

## 为什么要做

L0 对照用的是 `wk.sh search`，绕过了 Twinbox 的三重门、`mail_ref` join 和 sidecar 回退。L2 要让用户在 Twinbox 里看到授权命中，而不是直接摸 WeKnora HTTP。

## 接口（拟定）

```text
twinbox weknora search --account-id <id> --query "<text>" [--limit N] [--json]
```

行为：

1. 读本地开关与 ADR 标记；任一未开 → 不发起网络，走 sidecar，结果标 `degraded=sidecar`。
2. 读 source grant；`mail_refs` 为空 → 同上。
3. 调用现有 `search_excerpts`（已有授权过滤与 join）。
4. 超时或 provider 失败 → sidecar，标降级原因有界码，不打印正文/密钥。
5. 命中只暴露：opaque `mail_ref`、knowledge_ref 前缀、可选 score、bounded excerpt；不混排会议库。

不在本命令范围：`sync`、`revoke`、改 grant、改调度。

## 三重门

与 sync 相同：`weknora.enabled` + `adr_004_accepted` + 有效 grant。缺一即 sidecar。

## 降级标记（JSON 字段）

| 字段 | 含义 |
|---|---|
| `source` | `weknora` / `sidecar` |
| `degraded` | bool |
| `degrade_reason` | `switch_off` / `no_grant` / `timeout` / `provider_failed` / `empty_mappings` |
| `hits` | 列表；每项含 `mail_ref`，不含 MIME |

## 测试清单（零真实网络）

1. 开关关 → sidecar，`degrade_reason=switch_off`。
2. grant 空 → sidecar，`no_grant`。
3. fake provider 命中 → `source=weknora`，`mail_ref` 在 grant 内。
4. fake provider 超时 → sidecar，`timeout`。
5. 会议库不出现在单次 search 路径（provider 实例只绑邮件 KB）。

## 实现落点（获授权后）

- 测试先写：`tests/test_weknora_search_cli.py`（或扩现有 search 测试）。
- 再改：`twinbox_core/cli.py` 增加 `weknora search` 子命令，复用 `search_excerpts` + factory。
- 不改：`config/schedules.yaml`、`imap_fetch.py`、日常 `thread`（那是 L3）。

## 停止条件

- L1 未证明摘录相对 sidecar 有增量时，可不实现 L2，保留适配器默认关。
- 任何实现 PR 默认关闭开关；现场试跑仍走隔离 workdir + 用完即撤，除非 owner 另定 retention。
