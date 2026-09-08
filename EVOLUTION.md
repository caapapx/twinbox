# Evolution notes (v0.3.0)

SpecKit 002–007 在 `master` 落地。权威仍是代码与 constitution 1.2.0。

## SYSTEM_PROMPT

- `waiting_on_me` 以线程最新一封为准；审批/同意应 `resolved_by_reply`，不得再 pending。
- `why` 必须引用提供的正文，禁止推测。
- 输入按 `thread_key` 分组并标记 `is_latest`。

## 回放

使用 `tests/eval_replay.py --root <state>`。真实邮件不进仓。Sprint 0 本机 `~/.twinbox` 仅作本地对照；239 状态根为 `/iflytek/server/qwenpaw/qwenpaw-data/twinbox-state`。

## 不迁

Go CLI、Himalaya、Unix-socket daemon、OpenClaw deploy/bridge/push、Phase 2 persona。
