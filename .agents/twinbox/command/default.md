# Twinbox MCP mode (platform-agnostic)

Twinbox on `main` is used through MCP, not the
legacy `twinbox ... --json` command families. Register the repository-root
`mcp-server.mjs` as a local stdio MCP server, then call the tools below by their
exact names.

## Tool map

- Latest mail / today snapshot: `twinbox_latest_mail`
  - Optional input: `{ "unread_only": true }`
  - Automatically syncs when the activity pulse is missing.
- Todo / urgent / pending replies: `twinbox_todo`
- Current weekly brief: `twinbox_weekly`
- Refresh mail and analysis: `twinbox_sync`
  - Optional input: `{ "job": "daytime-sync" }` or `{ "job": "nightly-full" }`
- Inspect/search a thread: `twinbox_thread_inspect`
  - Required input: `{ "query": "..." }`
- Local queue action: `twinbox_queue_action`
  - Required inputs: `action` (`complete`, `dismiss`, or `restore`) and
    `thread_key`; optional `reason`.
- Historical/targeted extraction: `twinbox_extract`
  - Supports `profile`, `since`, `until`, `folders`, `subject_contains`,
    `subject_regex`, `body_contains`, `weekdays`, `from_self`, and `bucket`.
- Mailbox health: `twinbox_status`
- Initial setup: `twinbox_setup`

## Rule

Call the matching MCP tool first and summarize the returned result afterward.
Use `twinbox_extract` for historical/keyword searches; it does not trigger a
sync. Default behavior is read-only for the real mailbox. `twinbox_queue_action`
only changes Twinbox's local queue state and does not send, delete, archive, or
mark-read email.

The MCP server accepts the IMAP and optional LLM environment variables described
in the repository `README.md`. Do not expose credentials in output.
