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

## Turn contract

For mail/queue/digest requests: run the matching `twinbox` command with `--json`, then reply with a text summary. Never end with only tool reads and no text response.

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
| Latest mail / today summary / "最新邮件情况" / 帮我查看下最新的邮件情况 | `twinbox task latest-mail --json` (use `--unread-only` if user asks for unread) |
| "我有哪些待办 / 待回复 / 最值得关注的线程" | `twinbox task todo --json` |
| "某个事情进展如何" / progress on a topic | `twinbox task progress QUERY --json` |
| Mailbox status / env diagnosis | `twinbox task mailbox-status --json` |
| Weekly brief lookup | `twinbox task weekly --json` |
| Manage semantic routing rules / "以后别把这类邮件派给我" | `twinbox rule list --json` / `twinbox rule add --rule-json ...` |
| Test a routing rule against recent threads | `twinbox rule test --rule-id RULE_ID --json` |
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
- For the latest mail situation (including casual Chinese variants), use `twinbox task latest-mail --json` first; do not start with `preflight` unless connectivity is the explicit problem. If the user explicitly asks for "未读" (unread), pass `--unread-only` to the command or `unread_only: true` to the tool.
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
