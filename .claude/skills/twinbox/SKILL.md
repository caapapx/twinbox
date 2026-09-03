---
name: twinbox
description: >-
  Twinbox MCP email skill. Use the twinbox_* MCP tools for mailbox setup,
  synchronization, latest-mail summaries, todo triage, thread inspection,
  historical extraction, weekly briefs, and local queue actions. CRITICAL:
  call the matching MCP tool FIRST, then write a visible summary based on its
  result. These are MCP tools, not shell commands. Stay read-only with respect
  to the real mailbox unless the user explicitly requests a future write
  capability; queue actions only change Twinbox's local queue state.
---

# Twinbox MCP skill

Twinbox is a thread-centric email copilot exposed through the local MCP stdio
server. For mailbox requests, use the MCP tool with the exact name below rather
than inventing a CLI subcommand or telling the user to run one.

## Required interaction rule

1. Identify the user's intent and call the matching `twinbox_*` MCP tool first.
2. Treat the returned JSON/text as the source of truth for the response.
3. Write a concise, visible summary after the tool returns. Include errors and
   recovery guidance when the tool reports them; do not claim a result that was
   not returned by the tool.
4. Never answer a mailbox data request with text only.

## Tool map

| User intent | MCP tool | Important inputs / behavior |
|---|---|---|
| Refresh mail and analysis | `twinbox_sync` | `job`: `daytime-sync` (default) or `nightly-full` |
| Latest mail / today snapshot | `twinbox_latest_mail` | Optional `unread_only`; automatically syncs when the activity pulse is missing |
| Todo / urgent / pending replies | `twinbox_todo` | Read-only queue snapshot |
| Current weekly brief | `twinbox_weekly` | Reads the latest sync artifacts; does not replace a historical extraction |
| Inspect or search a thread | `twinbox_thread_inspect` | Required `query`: subject fragment, thread key, or keyword |
| Complete, dismiss, or restore a queue item | `twinbox_queue_action` | Required `action` (`complete`, `dismiss`, `restore`) and `thread_key`; optional `reason` |
| Historical or targeted mail extraction | `twinbox_extract` | `profile`, `since`, `until`, `folders`, `subject_contains`, `subject_regex`, `body_contains`, `weekdays`, `from_self`, `bucket` |
| Mailbox health / configuration check | `twinbox_status` | No inputs; checks IMAP, LLM validation, and artifacts |
| Initial setup | `twinbox_setup` | No inputs; validates environment-backed IMAP and LLM setup |

## Choosing between tools

- Use `twinbox_latest_mail` for the latest activity. It handles a missing
  `activity-pulse.json` by running the recovery sync internally; do not tell the
  user to sync first.
- Use `twinbox_sync` when the user explicitly asks to refresh/rebuild data, or
  when another tool reports a recovery request and the tool itself cannot
  recover.
- Use `twinbox_weekly` for the current sync-produced weekly brief.
- Use `twinbox_extract` for historical reports or targeted searches by date,
  folder, sender, subject, body, weekday, or profile. It does **not** trigger a
  daily sync.
- Use `twinbox_thread_inspect` for a specific topic/thread and summarize the
  returned evidence rather than guessing progress.
- After a user confirms that a queue item is complete, ignored, or should be
  restored, call `twinbox_queue_action` and report the persisted local result.

## Safety and scope

- Twinbox currently reads IMAP and performs local analysis. Default behavior is
  read-only for the real mailbox.
- `twinbox_queue_action` changes only Twinbox's local queue visibility/state. It
  does not send, delete, archive, mark-read, or otherwise mutate a real email.
- Do not invent or promise send/reply/draft/archive/delete actions that are not
  exposed by the current MCP server.
- Do not expose credentials in summaries. Setup/status output may contain masked
  configuration and health information; preserve that masking.

## MCP connection

The MCP server is `mcp-server.mjs` at the repository root. A client should
register it as a local stdio server with `node`, an absolute path to that file,
and the repository as `cwd`. IMAP credentials are supplied through the
connection environment (`IMAP_HOST`, `IMAP_PORT`, `IMAP_ENCRYPTION`,
`IMAP_LOGIN`, `IMAP_PASS`, `MAIL_ADDRESS`); optional state/code-root and LLM
environment variables are documented in `README.md`.

Do not use the obsolete CLI command families from the pre-MCP line; `main`
exposes the `twinbox_*` MCP tools instead.
