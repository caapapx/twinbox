---
name: twinbox
description: >-
  Twinbox mailbox skill for read-only email preflight, queue triage, phase
  refresh, and OpenClaw deployment diagnostics via `twinbox` and
  `twinbox-orchestrate`.
metadata: {"openclaw":{"requires":{"env":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS"]},"primaryEnv":"IMAP_LOGIN","login":{"mode":"password-env","runtimeRequiredEnv":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"],"optionalDefaults":{"MAIL_ACCOUNT_NAME":"myTwinbox","MAIL_DISPLAY_NAME":"{MAIL_ACCOUNT_NAME}","IMAP_ENCRYPTION":"tls","SMTP_ENCRYPTION":"tls"},"stages":["unconfigured","validated","mailbox-connected"],"preflightCommand":"twinbox mailbox preflight --json"},"schedules":[{"name":"daily-refresh","cron":"30 8 * * *","command":"twinbox-orchestrate run --phase 4","description":"Daily pre-computation of urgent/pending/sla queues at 08:30"},{"name":"weekly-refresh","cron":"30 17 * * 5","command":"twinbox-orchestrate run --phase 4","description":"Weekly brief refresh every Friday at 17:30"},{"name":"nightly-full-refresh","cron":"0 2 * * *","command":"twinbox-orchestrate run","description":"Nightly full pipeline refresh at 02:00"}]}}
---

# twinbox

Use this skill for Twinbox mailbox onboarding, read-only preflight checks, queue refresh, and deployment debugging in OpenClaw-managed environments.

## Use For

- Mailbox env collection and login preflight via `twinbox mailbox preflight --json`
- Checking whether Twinbox runtime is mounted and runnable in the current OpenClaw host
- Refreshing pipeline artifacts with `twinbox-orchestrate run --phase <n>`
- Explaining urgent / pending / SLA / weekly outputs under `runtime/validation/phase-4/`
- Diagnosing why a deployed Twinbox/OpenClaw skill is still missing, blocked, stale, or not refreshing

## Guardrails

- Stay read-only by default
- Do not send, delete, archive, or mutate mailbox state unless the user explicitly requests it and the runtime supports it
- Do not claim `metadata.openclaw.schedules` is executing unless you verify it in the current platform

## Fast Checks

- `twinbox mailbox preflight --json`
- `twinbox-orchestrate roots`
- `twinbox-orchestrate contract --phase 4`
- `twinbox-orchestrate run --phase 1`
- `twinbox-orchestrate run --phase 4`

## Runtime Notes

- `mailbox-connected` means read-only IMAP preflight succeeded
- `status=warn` with `smtp_skipped_read_only` is acceptable for preflight
- If Twinbox commands fail, first verify env, mounted repo root, `runtime/bin/himalaya`, and Python dependencies on the OpenClaw host

**Claude Code skill (deeper repo workflow):** [`.claude/skills/twinbox/SKILL.md`](.claude/skills/twinbox/SKILL.md)
