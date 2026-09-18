# Feature Specification: Unread FLAGS + queue visibility

**Feature Directory**: `specs/012-unread-flags-queue-visibility`

**Created**: 2026-09-16

**Status**: Draft (thin contract)

**Type**: `feature`

**Input**: Incremental IMAP only FETCHes new UIDs, so FLAGS freeze; `\Seen` is stored with a backslash while pulse/select compare bare `Seen`; `queue_action` writes local YAML but does not rebuild pulse, so completed threads stay on latest/todo until the next sync.

## What / Why

Mailbox owners mark mail read in Outlook/phone, or mark a thread done in Twinbox. Query tools (`latest_mail unread_only`, `todo`) must reflect that without writing IMAP `\Seen` (constitution Principle I) and without treating FLAGS-only changes as new mail for LLM analysis.

## User-visible behavior

1. `twinbox_sync` (`daytime-sync`, `quick-refresh`, `nightly-full`) refreshes FLAGS for lookback envelopes already on disk (read-only `UID FETCH … (FLAGS)`). Outlook/phone `\Seen` updates appear in pulse `unread_count` after sync.
2. FLAGS-only changes never enter `new_envelope_ids` / never force `analysis_path=incremental`.
3. Stored flags are canonical (`Seen`, not `\Seen`) so unread checks are correct.
4. `twinbox_queue_action` complete/dismiss/restore rebuilds activity-pulse immediately; `latest_mail` / `todo` hide completed/dismissed threads. Pulse `generated_at`, `fetch_at`, `analysis_generated_at`, `source_account`, and `stale_analysis` stay the previous IMAP/analysis lineage (staleness not washed). Rebuild failure keeps the prior snapshot and still hides via local queue YAML.
5. `twinbox_thread_inspect` still finds hidden threads (inspect ≠ done).
6. No IMAP STORE / flag / move / send.
7. Pulse publish uses same-directory temp + replace under a per-account lock so queue rebuild and sync cannot clobber each other. Projection attach failures are written to `diagnostics.projection_error`; the base snapshot remains readable.

## Acceptance

- Decode `FLAGS (\\Seen)` → envelope `flags` contains `"Seen"`; `"Seen" not in flags` is false.
- FLAGS refresh updates an old UID from unread → Seen; `new_envelope_ids` stays empty; noop daytime still `analysis_path=skip`.
- After `queue_action complete`, `latest_mail(unread_only=True)` and `todo` omit that `thread_key`; `generated_at` unchanged; `thread_inspect` still returns it.
- Queue rebuild preserves `source_account` / `stale_analysis` / `fetch_at` / `analysis_generated_at`; `account_freshness` reads those fields, not pulse file mtime.
- Pulse write failure: local complete/dismiss still `ok`, `pulse_updated=false`, prior snapshot remains; latest/todo still hide via queue YAML.
- phase1 gate: no STORE / APPEND / EXPUNGE in `imap_fetch.py`.
- Query path still does not IMAP when pulse is only stale (002 FR-006).

## Boundaries

- No new MCP tools. No write-back `\Seen` (Planned `006`).
- `thread_inspect` does not mark read or hide threads.
- Do not mix with accounts/vault WIP or compressor / select threshold changes.
- Constitution I: default mailbox remains read-only.
