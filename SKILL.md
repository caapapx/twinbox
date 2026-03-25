---
name: twinbox
description: >-
  Twinbox mailbox skill for read-only email preflight, latest-mail summaries,
  queue triage, pending replies, thread progress, weekly brief, phase refresh,
  and OpenClaw deployment diagnostics via `twinbox` and
  `twinbox-orchestrate`.
metadata: {"openclaw":{"requires":{"env":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"]},"primaryEnv":"IMAP_LOGIN","login":{"mode":"password-env","runtimeRequiredEnv":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"],"optionalDefaults":{"MAIL_ACCOUNT_NAME":"myTwinbox","MAIL_DISPLAY_NAME":"{MAIL_ACCOUNT_NAME}","IMAP_ENCRYPTION":"tls","SMTP_ENCRYPTION":"tls"},"stages":["unconfigured","validated","mailbox-connected"],"preflightCommand":"twinbox mailbox preflight --json"},"schedules":[{"name":"daily-refresh","cron":"30 8 * * *","command":"twinbox-orchestrate run --phase 4","description":"Daily pre-computation of urgent/pending/sla queues at 08:30"},{"name":"weekly-refresh","cron":"30 17 * * 5","command":"twinbox-orchestrate run --phase 4","description":"Weekly brief refresh every Friday at 17:30"},{"name":"nightly-full-refresh","cron":"0 2 * * *","command":"twinbox-orchestrate run","description":"Nightly full pipeline refresh at 02:00"}]}}
---

# twinbox

Use this skill for Twinbox mailbox onboarding, read-only preflight checks, latest-mail summaries, queue triage, thread progress lookup, weekly digest lookup, queue refresh, and deployment debugging in OpenClaw-managed environments.

## Use For

- Mailbox env collection and login preflight via `twinbox mailbox preflight --json`
- Summarizing "latest mail situation", "today's updates", or "what happened today"
- Listing urgent items, pending replies, and SLA-ish risks from current artifacts
- Looking up the latest progress of one thread, subject, project, or business keyword
- Showing daily / pulse / weekly digests from current Twinbox artifacts
- Suggesting actions or review items from current queue state
- Checking whether Twinbox runtime is mounted and runnable in the current OpenClaw host
- Refreshing pipeline artifacts with `twinbox-orchestrate run --phase <n>`
- Explaining urgent / pending / SLA / weekly outputs under `runtime/validation/phase-4/`
- Diagnosing why a deployed Twinbox/OpenClaw skill is still missing, blocked, stale, or not refreshing

## Task Entrypoints

For task requests, do not stop after reading this `SKILL.md`. Execute the matching Twinbox command and answer from its output.

- Latest mail / today summary / "最新邮件情况" -> `twinbox task latest-mail --json`
- "我有哪些待办 / 待回复 / 最值得关注的线程" -> `twinbox task todo --json`
- "某个事情进展如何" -> `twinbox task progress QUERY --json`
- Mailbox status / env diagnosis -> `twinbox task mailbox-status --json`
- Weekly brief lookup -> `twinbox task weekly --json`
- Inspect one exact thread -> `twinbox thread inspect THREAD_ID --json`
- Explain why a thread is urgent / pending -> `twinbox thread explain THREAD_ID --json`
- Daily digest -> `twinbox digest daily --json`
- Weekly brief -> `twinbox digest weekly --json`
- Suggest next actions -> `twinbox action suggest --json`
- Materialize one suggested action -> `twinbox action materialize ACTION_ID --json`
- Review items -> `twinbox review list --json` / `twinbox review show REVIEW_ID --json`
- Refresh hourly/daytime projection -> `twinbox-orchestrate schedule --job daytime-sync --format json`
- Refresh full nightly/weekly pipeline -> `twinbox-orchestrate schedule --job nightly-full --format json` or `twinbox-orchestrate schedule --job friday-weekly --format json`

## Task Routing Rules

- Prefer `--json`, then summarize the result for the user
- Prefer `twinbox task ...` for common OpenClaw user prompts; these are thin wrappers over existing Twinbox views, not a second pipeline
- If the user asks for the latest mail situation, prefer `twinbox task latest-mail --json`; do not start with `preflight` unless connectivity/config is the user's problem
- If `activity-pulse.json` is missing or stale, explain that the pulse projection needs refresh and then run or recommend `twinbox-orchestrate schedule --job daytime-sync`
- If the user asks to send/reply/draft, stay read-only unless they explicitly ask for draft/action generation
- Do not answer task requests with a paraphrase of this skill file when a Twinbox command can be executed instead

## Guardrails

- Stay read-only by default
- Do not send, delete, archive, or mutate mailbox state unless the user explicitly requests it and the runtime supports it
- Do not claim `metadata.openclaw.schedules` is executing unless you verify it in the current platform

## Fast Checks

- `twinbox task mailbox-status --json`
- `twinbox task latest-mail --json`
- `twinbox task todo --json`
- `twinbox task progress QUERY --json`
- `twinbox-orchestrate roots`
- `twinbox-orchestrate contract --phase 4`
- `twinbox-orchestrate run --phase 1`
- `twinbox-orchestrate run --phase 4`

## Runtime Notes

- `mailbox-connected` means read-only IMAP preflight succeeded
- `status=warn` with `smtp_skipped_read_only` is acceptable for preflight
- OpenClaw-native deployments should inject mailbox env into process env; `state root/.env` is a local fallback, not the preferred hosted config source
- If Twinbox commands fail, first verify env, mounted repo root, `runtime/bin/himalaya`, and Python dependencies on the OpenClaw host

**Claude Code skill (deeper repo workflow):** [`.claude/skills/twinbox/SKILL.md`](.claude/skills/twinbox/SKILL.md)
