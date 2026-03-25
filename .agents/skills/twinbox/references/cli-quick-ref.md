# CLI Quick Reference

> Distilled from `docs/ref/cli.md` for on-demand load with the twinbox Claude Code skill.
> Full spec: `docs/ref/cli.md`; drift notes: `docs/ref/drift-inventory.md`.

## 入口说明

| 入口 | 用途 |
|------|------|
| `twinbox` | task-facing CLI（队列/线程/摘要/行动/审核/上下文/邮箱） |
| `twinbox-orchestrate` | 编排 CLI（phase 运行，独立二进制） |

## 已验证命令（MVP）

### 读路径（无副作用，可直接调用）

```bash
twinbox mailbox preflight --json            # 邮箱登录预检
twinbox queue list --json                   # 全部队列概览
twinbox queue show urgent --json            # 队列详情（urgent/pending/sla_risk）
twinbox thread inspect THREAD_ID --json     # 线程状态
twinbox thread explain THREAD_ID --json     # 线程推断依据
twinbox digest daily --json                 # 每日摘要
twinbox digest weekly --json                # 每周简报
twinbox rule list --json                    # 语义分拣规则列表
twinbox rule test --rule-id RULE_ID --json  # 规则回测
twinbox action suggest --json               # 行动建议列表
twinbox action materialize ACTION_ID --json # 行动详情
twinbox review list --json                  # 待审核列表
twinbox review show REVIEW_ID --json        # 审核项详情
```

### 写路径（有副作用，建议二次确认）

```bash
twinbox context import-material SOURCE              # 位置参数，非 --file
twinbox context upsert-fact --id ID --type T --content C
twinbox context profile-set PROFILE --key K --value V
twinbox rule add --rule-json '{"name": "...", "conditions": {...}, "actions": {...}}'
twinbox rule remove RULE_ID
```

### 编排路径

```bash
twinbox-orchestrate run --phase 4   # 仅 Phase 4（快速刷新队列/摘要投影，~2min）
twinbox-orchestrate run             # 全量 Phase 1–4（不传 --phase 即顺序跑满）
```

### 🚧 未实现（勿调用）

`thread summarize` / `action apply` / `review approve` / `review reject`

## 退出码

| 码 | 含义 |
|----|------|
| 0 | 成功（含只读 SMTP warn） |
| 1 | 业务错误（未找到线程/队列） |
| 2 | 配置缺失（missing_env） |
| 3 | IMAP 网络/TLS 失败 |
| 4 | IMAP 认证失败 |
| 5 | 内部错误（himalaya 缺失等） |

## 关键 JSON 字段

### mailbox preflight

```json
{
  "login_stage": "unconfigured | validated | mailbox-connected",
  "status": "success | warn | fail",
  "missing_env": [],
  "actionable_hint": "用户可读修复提示",
  "next_action": "下一步建议"
}
```

### queue list

```json
[
  {
    "queue_type": "urgent | pending | sla_risk",
    "items": [...],
    "generated_at": "ISO 8601",
    "stale": true
  }
]
```

### ThreadCard（queue/thread 命令共用）

```json
{
  "thread_id": "string",
  "state": "string",
  "waiting_on": "string",
  "last_activity_at": "ISO 8601 | null",
  "confidence": 0.85,
  "evidence_refs": ["envelope-5"],
  "context_refs": ["escalation-policy"],
  "why": "string"
}
```
