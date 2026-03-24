---
name: email-himalaya-assistant
description: Thread-centric email copilot for OpenClaw that learns workflow from mailbox evidence, human context, and controlled automation.
metadata: {"openclaw":{"requires":{"env":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS"]},"primaryEnv":"IMAP_LOGIN","login":{"mode":"password-env","runtimeRequiredEnv":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"],"optionalDefaults":{"MAIL_ACCOUNT_NAME":"myTwinbox","MAIL_DISPLAY_NAME":"{MAIL_ACCOUNT_NAME}","IMAP_ENCRYPTION":"tls","SMTP_ENCRYPTION":"tls"},"stages":["unconfigured","validated","mailbox-connected"],"preflightCommand":"twinbox mailbox preflight --json"},"schedules":[{"name":"daily-refresh","cron":"30 8 * * *","command":"twinbox orchestrate run phase4","description":"Daily pre-computation of urgent/pending/sla queues at 08:30"},{"name":"weekly-refresh","cron":"30 17 * * 5","command":"twinbox orchestrate run phase4","description":"Weekly brief refresh every Friday at 17:30"},{"name":"nightly-full-refresh","cron":"0 2 * * *","command":"twinbox orchestrate run phase1 phase2 phase3 phase4","description":"Nightly full pipeline refresh at 02:00"}]}}
---

Use this skill for mailbox onboarding, thread-state triage, daily queue generation, and draft-safe email workflows.

## Scope

- Read and summarize mailbox messages
- Reconstruct thread-level workflow state
- Build daily and weekly value surfaces
- Generate draft replies behind explicit review
- Ingest user-supplied context such as recurring habits and work materials

## Out of Scope

- No auto-send unless user explicitly confirms and policy allows it
- No mailbox deletion or destructive cleanup
- No third-party exfiltration of raw email body without approval

## Expected Environment

- Mailbox credentials loaded from `.env` or injected as environment variables
- Runtime-required mailbox keys: `IMAP_HOST`, `IMAP_PORT`, `IMAP_LOGIN`, `IMAP_PASS`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_LOGIN`, `SMTP_PASS`, `MAIL_ADDRESS`
- Defaulted keys: `MAIL_ACCOUNT_NAME=myTwinbox`, `MAIL_DISPLAY_NAME={MAIL_ACCOUNT_NAME}`, `IMAP_ENCRYPTION=tls`, `SMTP_ENCRYPTION=tls`
- Runtime config generated at `runtime/himalaya/config.toml`
- Validation outputs and context artifacts kept under `runtime/`

## Mailbox Login Status

- `unconfigured`: missing required mailbox settings
- `validated`: mailbox settings resolved and himalaya config rendered
- `mailbox-connected`: read-only IMAP preflight succeeded

## Suggested Tooling

- `scripts/check_env.sh`: validate env keys
- `scripts/render_himalaya_config.sh`: render backend config
- `twinbox mailbox preflight --json`: structured read-only mailbox preflight for OpenClaw
- `scripts/preflight_mailbox_smoke.sh`: compatibility wrapper around the mailbox preflight command

## Trigger Phrases

- "sync my mailbox"
- "scan unread emails"
- "triage today's emails"
- "what am I waiting on"
- "generate weekly email digest"
- "draft a reply to this thread"
