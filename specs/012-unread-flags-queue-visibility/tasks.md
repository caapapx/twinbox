# Tasks: Unread FLAGS + queue visibility

- [x] T001 Thin spec (this directory)
- [x] T002 Canonicalize IMAP flags (`\Seen` → `Seen`) in decode / normalize; pulse & select use same rule
- [x] T003 `fetch_incremental`: read-only FLAGS refresh for lookback UIDs; not in `new_envelope_ids`; optional `flags_refreshed_count`
- [x] T004 `cmd_queue_action`: rebuild pulse keeping prior `generated_at`; latest/todo filter hidden; inspect does not
- [x] T005 Tests + SKILL two-line guidance; phase1 STORE ban still green
- [x] T006 Atomic pulse publish + lineage on queue rebuild; freshness from artifact timestamps; projection_error diagnostics (`tests/test_queue_visibility.py`)
