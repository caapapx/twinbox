---
name: twinbox
description: >-
  Twinbox mailbox skill. Use this for mailbox onboarding, preflight checks,
  latest-mail summaries, queue triage, thread progress, weekly digests,
  queue refresh, schedule management, and deployment debugging.
  Always run the matching twinbox command with --json FIRST,
  then write a text summary. Never narrate without executing.
  For latest mail: run twinbox task latest-mail --json immediately.
  For todo: run twinbox task todo --json. Never end a turn with only
  text when the user asked for mail, todo, digest, or onboarding action.
  If activity-pulse.json is missing, run daytime-sync first then retry.
  Stay read-only unless user explicitly asks for draft/action generation.
---

# twinbox

Twinbox is a thread-centric email Copilot. Use this skill for all mailbox-related tasks.

## Required Steps for Any Task

1. Match the user's request to a command below.
2. Execute that command with `--json`.
3. Write a text answer summarizing the real output.

## Task Entrypoints

| User intent | Command |
|---|---|
| Latest mail / today summary | `twinbox task latest-mail --json` |
| Todo / pending replies | `twinbox task todo --json` |
| Thread progress | `twinbox task progress QUERY --json` |
| Weekly brief | `twinbox task weekly --json` |
| Mailbox status / env diagnosis | `twinbox task mailbox-status --json` |
| Daily digest | `twinbox digest daily --json` |
| Weekly digest | `twinbox digest weekly --json` |
| Queue dismiss | `twinbox queue dismiss THREAD_ID --reason "..." --json` |
| Queue complete | `twinbox queue complete THREAD_ID --action-taken "..." --json` |
| Queue restore | `twinbox queue restore THREAD_ID --json` |
| Schedule list | `twinbox schedule list --json` |
| Schedule enable/disable | `twinbox schedule enable\|disable JOB_NAME --json` |
| Inspect thread | `twinbox thread inspect THREAD_ID --json` |
| Explain thread | `twinbox thread explain THREAD_ID --json` |
| Suggest actions | `twinbox action suggest --json` |
| Review items | `twinbox review list --json` |
| Import material | `twinbox context import-material FILE --intent reference --json` |
| Onboarding start/status/next | `twinbox onboarding start\|status\|next --json` |
| Preflight | `twinbox mailbox preflight --json` |
| Config show | `twinbox config show --json` |
| Daemon status | `twinbox daemon status --json` |

## Guardrails

- Stay read-only by default (IMAP is read-only in Phase 1-4)
- `queue complete`/`queue dismiss` only update local queue visibility
- Do not send, delete, archive, or mutate mailbox state unless explicitly requested
- Never end a task turn with only file reads and no text answer
- If `activity-pulse.json` is missing/stale, run `twinbox-orchestrate schedule --job daytime-sync` then retry

## Runtime Notes

- State root: `~/.twinbox` (config: `~/.twinbox/twinbox.json`)
- Code root: `~/.config/twinbox/code-root`
- Daemon socket: `$TWINBOX_STATE_ROOT/run/daemon.sock`
- Vendor install: `twinbox vendor install`; status: `twinbox vendor status --json`
