# AGENTS.md — twinbox

## Project Overview

Twinbox is a thread-centric email Copilot CLI. Use this skill for all mailbox-related tasks.

## Critical Rule

**Always run the matching twinbox command with --json FIRST, then write a text summary.**

Never narrate "let me run" or "need to sync first" without executing a command in the same turn.

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
