---
name: twinbox
description: >-
  Expert for this repo's mailbox pipeline and CLI: `twinbox` (preflight, queues
  urgent/pending/sla, thread inspect/explain, daily/weekly digest, action
  suggest/materialize, review list/show, context import/profile) and
  `twinbox-orchestrate` (phase1-4 refresh, stale projections). Interprets JSON
  from `--json`, `login_stage`, exit codes 2-5, `stale` flags, `runtime/` and
  Himalaya config, IMAP read-only rules, and draft-safe boundaries. Use for any
  task in the twinbox codebase that touches mailbox connectivity, triage,
  "what am I waiting on", SLA-ish queues, standup rollups, orchestration
  refresh, env var gaps, or slash commands `/twinbox-*`—even if the user never
  says "twinbox". Do not use for generic Git, Docker, pytest, or unrelated
  refactors with no mail/CLI artifact angle.
---

# twinbox (Codex skill)

Use this skill for mailbox onboarding, thread-state triage, queue surfaces, digest generation, and draft-safe email workflows **in this repository**.

Prefer **slash commands** under `.Codex/commands/twinbox-*.md` when the user already names a flow (`/twinbox-queue`, `/twinbox-mailbox`, etc.); use this skill for ad-hoc tasks and when combining several CLI steps.

## Scope

- Read and summarize mailbox-backed artifacts (queues, threads, digests)
- Reconstruct thread-level workflow state from CLI JSON
- Run read-only mailbox preflight and interpret `login_stage`
- Guide context import / profile updates when the user explicitly wants writes
- Generate or refine drafts; never send without explicit user confirmation and policy

## Out of scope

- No auto-send unless the user explicitly confirms and policy allows
- No mailbox deletion, move, archive, or destructive cleanup via automation
- No exfiltration of raw email bodies to third parties without approval

## Expected environment

- Mailbox credentials in `.env` or injected env vars
- Runtime-required keys: `IMAP_HOST`, `IMAP_PORT`, `IMAP_LOGIN`, `IMAP_PASS`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_LOGIN`, `SMTP_PASS`, `MAIL_ADDRESS`
- Defaults: `MAIL_ACCOUNT_NAME=myTwinbox`, `MAIL_DISPLAY_NAME` derived, `IMAP_ENCRYPTION=tls`, `SMTP_ENCRYPTION=tls`
- Himalaya config at `runtime/himalaya/config.toml`; artifacts under `runtime/`

## Mailbox login stages

- `unconfigured`: missing required mailbox settings
- `validated`: settings resolved and config rendered; IMAP not yet verified
- `mailbox-connected`: read-only IMAP preflight succeeded

## Tooling

- `scripts/check_env.sh` — env key validation
- `scripts/render_himalaya_config.sh` — render backend config
- `twinbox mailbox preflight --json` — structured mailbox preflight
- `scripts/preflight_mailbox_smoke.sh` — shell wrapper around preflight

## Bundled references

Read these when you need exact commands, exit codes, or preflight JSON shapes:

- `references/cli-quick-ref.md` — MVP command list, exit codes, key JSON patterns
- `references/login.md` — login state machine, env vars, read-only boundaries

## Evaluation (中文全链路)

- `evals/full-chain-2026-03-24.json` — 中文用户提问版全链路测试集（`live_steps[].user_prompt_zh` 与 CLI 逐步对照；含合成夹具与离线 FO/LC 题）
- `evals/run-full-chain-live.sh` — 从该 JSON 读取 `user_prompt_zh` 并执行只读命令（仓库根目录下运行）

## Trigger phrases (examples)

- "sync my mailbox"
- "scan unread emails"
- "triage today's emails"
- "what am I waiting on"
- "generate weekly email digest"
- "draft a reply to this thread"
- "add a routing rule"
- "test this email rule"
