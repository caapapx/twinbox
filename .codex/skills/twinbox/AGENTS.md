# AGENTS.md — twinbox MCP skill

Twinbox is a thread-centric email copilot exposed through the local MCP stdio
server. The `master` branch registers the baseline twinbox_* tools plus additive
accounts/ingest/events tools. Use those registered tools directly; do not use
the obsolete CLI command families from older Twinbox versions.

## Critical rule

**Call the matching `twinbox_*` MCP tool first, then summarize its returned
JSON/text.** Never answer a request for mailbox data with text only, and never
claim that an action happened unless the tool returned a successful result.

## Tool map

| User intent | MCP tool | Inputs / behavior |
|---|---|---|
| Refresh mail and analysis | `twinbox_sync` | `job`: `daytime-sync` or `nightly-full` |
| Latest mail / today snapshot | `twinbox_latest_mail` | Optional `unread_only`; auto-syncs if activity data is missing |
| Todo / urgent / pending replies | `twinbox_todo` | Read-only |
| Current weekly brief | `twinbox_weekly` | Current sync artifact |
| Inspect/search thread | `twinbox_thread_inspect` | `query` is required |
| Complete/dismiss/restore local queue item | `twinbox_queue_action` | `action`, `thread_key`, optional `reason` |
| Historical/targeted extraction | `twinbox_extract` | Date, folder, keyword, profile, weekday, sender, and bucket filters |
| Mailbox health | `twinbox_status` | Optional `account_id`; includes per-account freshness / recent runs |
| Initial setup | `twinbox_setup` | No inputs |
| List/add/remove accounts | `twinbox_accounts` | Credentials stay in vault; outputs only `password_set` |
| Reference-only ingest | `twinbox_ingest` | Optional `account_id`, `since` cursor, `limit` |
| Event records | `twinbox_events` | Optional `account_id`, `limit` |

## Operating rules

- Use `twinbox_latest_mail` for latest activity. It performs the missing-pulse
  recovery sync itself; do not ask the user to sync first.
- Use `twinbox_sync` for an explicit refresh/rebuild (`daytime-sync` by default,
  `nightly-full` for a complete rebuild).
- Use `twinbox_weekly` for the current sync-produced brief; use
  `twinbox_extract` for historical or keyword-filtered reports. Extraction does
  not refresh the daily pulse.
- Use `twinbox_thread_inspect` for thread evidence and
  `twinbox_queue_action` when a user confirms a local queue state change.
- Default to read-only behavior. Queue actions modify only Twinbox's local
  queue visibility/state; they do not send, delete, archive, mark-read, or
  otherwise modify the real mailbox.
- Do not invent tools for sending, drafting, scheduling, daemon control, or
  mailbox mutation beyond the registered dry-run action review tools.
- Never reveal IMAP/LLM credentials. Preserve masked setup/status output;
  prefer `password_set` booleans.

The MCP server entrypoint is the repository-root `mcp-server.mjs`; see
`README.md` for stdio registration and environment variables.
