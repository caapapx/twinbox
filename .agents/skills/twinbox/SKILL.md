---
name: twinbox
description: >-
  Twinbox mailbox skill for read-only email preflight, latest-mail summaries,
  queue triage, pending replies, thread progress, weekly brief, phase refresh,
  and OpenClaw deployment diagnostics via `twinbox` and
  `twinbox-orchestrate`.
metadata: {"openclaw":{"requires":{"env":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"]},"primaryEnv":"IMAP_LOGIN","login":{"mode":"password-env","runtimeRequiredEnv":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"],"optionalDefaults":{"MAIL_ACCOUNT_NAME":"myTwinbox","MAIL_DISPLAY_NAME":"{MAIL_ACCOUNT_NAME}","IMAP_ENCRYPTION":"tls","SMTP_ENCRYPTION":"tls"},"stages":["unconfigured","validated","mailbox-connected"],"preflightCommand":"twinbox mailbox preflight --json"}}}
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
- Dismissing, completing, or restoring queue-visible threads through `twinbox queue ...`
- Listing, overriding, or resetting runtime schedule config through `twinbox schedule ...`
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
| 最新未读邮件 / 未读 / 只看未读 / 「不要已读的」 | `twinbox task latest-mail --unread-only --json` **或** OpenClaw 工具 `twinbox_latest_mail` 且 **`unread_only: true`**（必须二选一执行，禁止只读 SKILL 就结束） |
| "我有哪些待办 / 待回复 / 最值得关注的线程" | `twinbox task todo --json` |
| 暂时忽略某个线程 / 标记已处理但先别再提醒 | `twinbox queue dismiss THREAD_ID --reason "..." --json`；OpenClaw 插件：`twinbox_queue_dismiss`（`thread_id`，可选 `reason`） |
| 标记某个线程已完成（须落库，聊天里打 ✅ 不算） | `twinbox queue complete THREAD_ID --action-taken "..." --json`；OpenClaw 插件：`twinbox_queue_complete`（`thread_id`，可选 `action_taken`） |
| 恢复一个 dismissed/completed 线程 | `twinbox queue restore THREAD_ID --json` |
| 查看当前调度配置 | `twinbox schedule list --json` 或 OpenClaw 工具 `twinbox_schedule_list` |
| 修改 daily/weekly/nightly 调度时间 | `twinbox schedule update JOB_NAME --cron "30 9 * * *" --json` 或 OpenClaw 工具 `twinbox_schedule_update` |
| 恢复某个调度到默认时间 | `twinbox schedule reset JOB_NAME --json` 或 OpenClaw 工具 `twinbox_schedule_reset` |
| "某个事情进展如何" / progress on a topic | `twinbox task progress QUERY --json` |
| Mailbox status / env diagnosis | `twinbox task mailbox-status --json` |
| Weekly brief lookup | `twinbox task weekly --json` |
| Manage semantic routing rules / "以后别把这类邮件派给我" | `twinbox rule list --json` / `twinbox rule add --rule-json ...` |
| Test a routing rule against recent threads | `twinbox rule test --rule-id RULE_ID --json` |
| Start onboarding flow | `twinbox onboarding start --json` |
| Check onboarding progress | `twinbox onboarding status --json` |
| Advance onboarding to next stage | `twinbox onboarding next --json` |
| Inspect one exact thread / “把这个线程内容返回给我看看” / “先读这个线程” | `twinbox thread inspect THREAD_ID --json` 或 OpenClaw 工具 `twinbox_thread_inspect` 且传 `thread_id` |
| Explain why a thread is urgent / pending | `twinbox thread explain THREAD_ID --json` |
| Daily digest | `twinbox digest daily --json` |
| Weekly brief | `twinbox digest weekly --json` |
| Suggest next actions | `twinbox action suggest --json` |
| Materialize one suggested action | `twinbox action materialize ACTION_ID --json` |
| Review items | `twinbox review list --json` / `twinbox review show REVIEW_ID --json` |
| Refresh hourly/daytime projection | `twinbox-orchestrate schedule --job daytime-sync --format json` |
| Refresh full nightly/weekly pipeline | `twinbox-orchestrate schedule --job nightly-full --format json` |

## Task Routing Rules

- When the user confirms a thread is **done** or **dismissed**, you must persist queue state: run `twinbox queue complete` / `queue dismiss` with `--json`, or call OpenClaw tools `twinbox_queue_complete` / `twinbox_queue_dismiss`. Resolve `thread_id` from `task todo`, `task latest-mail`, or `thread inspect` — freeform weekly-brief lines alone are not thread keys.
- The file `runtime/context/user-queue-state.yaml` is **created on the first successful** `queue complete` or `queue dismiss`; absence before that is normal.
- Run the command first (`--json`), then summarize stdout in plain text for the user
- Prefer `twinbox task ...` for common user prompts; these are thin wrappers, not a second pipeline
- For the latest mail situation (including casual Chinese variants), use `twinbox task latest-mail --json` first; do not start with `preflight` unless connectivity is the explicit problem. If the user explicitly asks for "未读" (unread), pass `--unread-only` to the command or `unread_only: true` to the tool.
- If the user wants one exact thread's content/details/status, prefer `twinbox thread inspect THREAD_ID --json` or `twinbox_thread_inspect`; do not use `task progress` unless the request is fuzzy/topic-based.
- If `activity-pulse.json` is missing or stale, run `twinbox-orchestrate schedule --job daytime-sync` and explain the refresh
- `daytime-sync` now enters through the incremental Phase 1 entrypoint (`scripts/phase1_incremental.sh`) before Phase 3/4 daytime projection
- The incremental Phase 1 path uses UID watermarks and automatically falls back to the existing full loader when `UIDVALIDITY` changes
- Default schedule definitions now live in `config/schedules.yaml`; `twinbox schedule update/reset` writes `runtime/context/schedule-overrides.yaml` and then attempts to sync the matching Twinbox OpenClaw cron job via `openclaw cron list/edit/add`
- If Gateway access fails, the command still preserves the runtime override and exposes `platform_sync.status=error` in JSON output
- For schedule prompts, prefer native OpenClaw tools `twinbox_schedule_list` / `twinbox_schedule_update` / `twinbox_schedule_reset` over generic `cron` or workspace search
- Stay read-only unless the user explicitly asks for draft/action generation
- **Never end a task turn with only file reads and no text answer.** A turn with `assistant.content=[]` or no text is a failure — always produce real command output followed by a summary
- **OpenClaw 模型偶发空回复**：若连续出现「有 token 但正文为空」，先**新开会话**再试；技能/工具更新后旧会话里的 `skillsSnapshot` 可能仍引用旧说明（见 Hosted Defaults）。

## Hosted Defaults

- Prefer a dedicated `twinbox` agent/session for Twinbox work; keep `main` for general chat
- After skill or env changes, use a fresh Twinbox session; `skillsSnapshot` can freeze old injection results
- Hosted env should come from `skills.entries.twinbox.env`; `state root/.env` is a local fallback, not the primary hosted config source
- Treat OpenClaw schedule execution as a Twinbox-managed bridge cron concern; current default definitions come from `config/schedules.yaml`, not skill metadata
- The currently verified refresh path is `openclaw cron -> system-event -> host bridge/poller -> twinbox-orchestrate schedule --job ...`

## Guardrails

- Stay read-only by default (mailbox IMAP remains read-only in Phase 1–4)
- `queue complete` / `queue dismiss` only update **local** Twinbox queue visibility (`user-queue-state.yaml`); use them when the user asks to stop reminders for a **specific thread** they name or confirm
- Do not send, delete, archive, or mutate mailbox state unless the user explicitly requests it and the runtime supports it
- Do not claim OpenClaw auto-imports schedule metadata; current verified schedule setup comes from `twinbox schedule update/reset` syncing bridge cron jobs
- Do not treat `openclaw skills info twinbox = Ready` as proof that the current session prompt already contains `twinbox`
- Do not claim the platform has automatically run `preflightCommand` unless you have evidence from a real execution path

## Fast Checks

- `twinbox task mailbox-status --json`
- `twinbox task latest-mail --json`
- `twinbox task todo --json`
- `twinbox queue dismiss THREAD_ID --reason "已处理" --json`
- `twinbox queue complete THREAD_ID --action-taken "已归档" --json`
- `twinbox queue restore THREAD_ID --json`
- `twinbox schedule list --json`
- `twinbox schedule update daily-refresh --cron "30 9 * * *" --json`
- `twinbox schedule reset daily-refresh --json`
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
