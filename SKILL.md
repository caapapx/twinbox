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

## Session and verification (mechanism, not IDE-specific)

Twinbox mail state is produced by **`twinbox` / `twinbox-orchestrate` on the OpenClaw host** and consumed inside a **`twinbox` agent session** (tool policy + session history + Gateway). Regressions such as empty assistant payloads, “read SKILL only”, or silent turns are addressed by **session design and test procedure** (fresh session when needed, bootstrap turn, split long suites, optional **`plugin-twinbox-task`** tools), documented in `openclaw-skill/prompt-test.md` and `scripts/run_openclaw_prompt_tests.py` — not by relabeling the client app.

## Turn contract (read this before you stop)

OpenClaw often ends a turn with **empty `assistant.content`** after a tool read of this file or memory: only `tool_use` blocks, **no Twinbox command run**, **no final user text**. That is a failed turn for the user.

- If the user message is about **mail status, latest mail, queues, digests, or thread progress**, you **must** run the matching **`twinbox` / `twinbox-orchestrate` command** (prefer `--json`), then **must** send a **normal text reply** that summarizes command output for the user. Paraphrasing this `SKILL.md` instead of running the command is wrong.
- **Do not** treat “I read the skill file” as task completion. **Do not** end the turn with tool reads alone.
- On failure, still reply in text (short stderr / exit meaning); never finish with an empty assistant message.

Chinese phrasing for latest-mail (same as English “latest mail situation”): e.g. 帮我查看下最新的邮件情况、最新邮件、今天邮件怎么样、邮箱里最近有什么 → **`twinbox task latest-mail --json`**, then summarize in Chinese from the JSON.

### Wrong pattern (shows up as “没结果” in chat UI)

The model sometimes replies with **only** “让我先查找 twinbox 的产物文件目录 / weekly brief 文件位置” and then **stops**. That is a **failed** turn.

- **Do not** start by searching the workspace, listing `runtime/`, or “finding where outputs live” for mail / todo / weekly / pulse questions.
- **Do not** use `read` on random paths as the first step when a **`twinbox task … --json`** command exists for that intent.
- **Do** run the matching Twinbox command **in the same turn**, **before** any optional file reads. If a native tool exists (e.g. `twinbox_latest_mail`, `twinbox_weekly`), prefer that over guessing paths.
- **Do not** tell the user that you “cannot use `exec`”. In this hosted Twinbox environment, the expected behavior is to run the available Twinbox command path and answer from the result. If one command path is unavailable, try another matching Twinbox command or native Twinbox tool before asking the user to paste JSON.

| User-ish behavior (bad) | Required first action |
|-------------------------|----------------------|
| “先找产物目录 / 输出在哪” | `twinbox task latest-mail --json` (or `weekly` / `todo` / `progress` / `mailbox-status` per intent) |
| Weekly brief audit (real vs synthetic) | `twinbox task weekly --json` first, then cite fields; do not hunt files first |

## Use For

- Mailbox env collection and login preflight via `twinbox mailbox preflight --json`
- Summarizing "latest mail situation", "today's updates", or "what happened today"
- Listing urgent items, pending replies, and SLA-ish risks from current artifacts
- Looking up the latest progress of one thread, subject, project, or business keyword
- Showing daily / pulse / weekly digests from current Twinbox artifacts
- Suggesting actions or review items from current queue state
- Checking whether Twinbox runtime is mounted and runnable in the current OpenClaw host
- Refreshing pipeline artifacts with `twinbox-orchestrate schedule --job ...` or `run --phase <n>`
- Explaining urgent / pending / SLA / weekly outputs under `runtime/validation/phase-4/`
- Diagnosing why a deployed Twinbox/OpenClaw skill is still missing, blocked, stale, or not refreshing

## Task Entrypoints

**REQUIRED STEPS for any task request:**

1. Match the user's request to a command in the list below.
2. Execute that command now.
3. Write a text answer summarizing the real output.

Reading this file is step 0 only. The turn is **not complete** until you have executed a command (step 2) and written a text answer (step 3). If you have only read files or memory so far, proceed to step 2 immediately — do not end the turn.

| User intent | Command |
|-------------|---------|
| Latest mail / today summary / "最新邮件情况" / 帮我查看下最新的邮件情况 | `twinbox task latest-mail --json` |
| "我有哪些待办 / 待回复 / 最值得关注的线程" | `twinbox task todo --json` |
| "某个事情进展如何" / progress on a topic | `twinbox task progress QUERY --json` |
| Mailbox status / env diagnosis | `twinbox task mailbox-status --json` |
| Weekly brief lookup | `twinbox task weekly --json` |
| Inspect one exact thread | `twinbox thread inspect THREAD_ID --json` |
| Explain why a thread is urgent / pending | `twinbox thread explain THREAD_ID --json` |
| Daily digest | `twinbox digest daily --json` |
| Weekly brief | `twinbox digest weekly --json` |
| Suggest next actions | `twinbox action suggest --json` |
| Materialize one suggested action | `twinbox action materialize ACTION_ID --json` |
| Review items | `twinbox review list --json` / `twinbox review show REVIEW_ID --json` |
| Refresh hourly/daytime projection | `twinbox-orchestrate schedule --job daytime-sync --format json` |
| Refresh full nightly/weekly pipeline | `twinbox-orchestrate schedule --job nightly-full --format json` |

## Task Routing Rules

- Run the command first (`--json`), then summarize stdout in plain text for the user
- Prefer `twinbox task ...` for common user prompts; these are thin wrappers, not a second pipeline
- For the latest mail situation (including casual Chinese variants), use `twinbox task latest-mail --json` first; do not start with `preflight` unless connectivity is the explicit problem
- If `activity-pulse.json` is missing or stale, run `twinbox-orchestrate schedule --job daytime-sync` and explain the refresh
- Stay read-only unless the user explicitly asks for draft/action generation
- **Never end a task turn with only file reads and no text answer.** A turn with `assistant.content=[]` or no text is a failure — always produce real command output followed by a summary

## Hosted Defaults

- Prefer a dedicated `twinbox` agent/session for Twinbox work; keep `main` for general chat
- After skill or env changes, use a fresh Twinbox session; `skillsSnapshot` can freeze old injection results
- Hosted env should come from `skills.entries.twinbox.env`; `state root/.env` is a local fallback, not the primary hosted config source
- Treat `metadata.openclaw.schedules` as a declaration layer unless you verify platform-side execution in the current deployment
- The currently verified refresh path is `openclaw cron -> system-event -> host bridge/poller -> twinbox-orchestrate schedule --job ...`

## Guardrails

- Stay read-only by default
- Do not send, delete, archive, or mutate mailbox state unless the user explicitly requests it and the runtime supports it
- Do not claim `metadata.openclaw.schedules` is executing unless you verify it in the current platform
- Do not treat `openclaw skills info twinbox = Ready` as proof that the current session prompt already contains `twinbox`
- Do not claim the platform has automatically run `preflightCommand` unless you have evidence from a real execution path

## Fast Checks

- `twinbox task mailbox-status --json`
- `twinbox task latest-mail --json`
- `twinbox task todo --json`
- `twinbox task progress QUERY --json`
- `twinbox digest pulse --json`
- `twinbox-orchestrate roots`
- `twinbox-orchestrate contract --phase 4`
- `twinbox-orchestrate schedule --job daytime-sync --format json`
- `twinbox-orchestrate run --phase 1`
- `twinbox-orchestrate run --phase 4`

## Runtime Notes

- `mailbox-connected` means read-only IMAP preflight succeeded
- `status=warn` with `smtp_skipped_read_only` is acceptable for preflight
- OpenClaw-native deployments should inject mailbox env into process env via `skills.entries.twinbox.env`; `state root/.env` is a local fallback, not the preferred hosted config source
- If Twinbox stops appearing in answers after a deploy, check env gating first, then session-level `skillsSnapshot`
- If Twinbox commands fail, first verify env, mounted repo root, `runtime/bin/himalaya`, and Python dependencies on the OpenClaw host

**Claude Code skill (deeper repo workflow):** [`.claude/skills/twinbox/SKILL.md`](.claude/skills/twinbox/SKILL.md)
