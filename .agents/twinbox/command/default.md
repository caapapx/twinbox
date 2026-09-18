# Twinbox MCP mode (platform-agnostic)

Twinbox on `master` is used through MCP, not the
legacy `twinbox ... --json` command families. Register the repository-root
`mcp-server.mjs` as a local stdio MCP server, then call the tools below by their
exact names.

## Tool map

- Latest mail / today snapshot: `twinbox_latest_mail`
  - Optional: `unread_only`, `account_id` (omit uses `default_account_id`)
  - Automatically syncs when the activity pulse is missing.
- Todo / urgent / pending replies: `twinbox_todo` (optional `account_id`)
- Current weekly brief: `twinbox_weekly` (optional `account_id`)
- Refresh mail and analysis: `twinbox_sync`
  - Optional `job`: `daytime-sync` / `nightly-full` / `quick-refresh`
  - Omit `account_id` to sync all accounts
- Inspect/search a thread: `twinbox_thread_inspect`
  - Required `query`; optional `account_id`
- Local queue action: `twinbox_queue_action`
  - Required `action` (`complete`, `dismiss`, or `restore`) and `thread_key`
- Historical/targeted extraction: `twinbox_extract` (optional `account_id`)
- Mailbox health: `twinbox_status` (optional `account_id`)
- Accounts: `twinbox_accounts` (`list` / `add` / `remove` / `set-default`)
- Initial setup: `twinbox_setup`

## Rule

Call the matching MCP tool first and summarize the returned result afterward.
Use `twinbox_extract` for historical/keyword searches; it does not trigger a
sync. Default behavior is read-only for the real mailbox. `twinbox_queue_action`
only changes Twinbox's local queue state and does not send, delete, archive, or
mark-read email.

The MCP server accepts the IMAP and optional LLM environment variables described
in the repository `README.md`. Do not expose credentials in output.
