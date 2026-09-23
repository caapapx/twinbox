# Tasks: Append-only Case Lifecycle Ledger

> Checklist: `[x]` = implemented in this round; `[ ]` = open (not done).

## Engine

- [x] T001 Add `twinbox_core/case_ledger.py` with `case_ledger_path`, `case_ref`, `load_records`, `ledger_error` surface.
- [x] T002 `append_record` appends one JSON line (locked + fsync) and never rewrites or deletes an earlier line.
- [x] T003 `current_view` returns latest `valid_from` per `(case_ref, attribute)`, skipping `needs_confirmation` and ignoring backfill.
- [x] T004 `legal_states` / `reopen_states` resolve an optional pack lifecycle, else the four default states.
- [x] T005 `append_record` marks illegal value / illegal `closed`→non-reopen transition `needs_confirmation` and does not make it current.
- [x] T006 `derive_case_states` / `sync_derived_states` derive the four states from existing analysis rows only (no LLM, no system-prompt edit); carry `stage_proposals` / `followup` when present.
- [x] T007 `drop_closed_from_attention` removes `closed` threads from pulse `needs_attention` while keeping `thread_index`.
- [x] T008 Wire `drop_closed_from_attention` into `pulse.build_activity_pulse` (fail-open, `case_ledger_error` in diagnostics).

## Tests

- [x] T009 `tests/test_case_ledger.py` — append does not rewrite old lines.
- [x] T010 `tests/test_case_ledger.py` — older `valid_from` does not replace a newer current value (backfill).
- [x] T011 `tests/test_case_ledger.py` — supersede only affects the same `case_ref`+`attribute`.
- [x] T012 `tests/test_case_ledger.py` — `closed` leaves `needs_attention` and remains queryable.
- [x] T013 `tests/test_case_ledger.py` — illegal value stored as `needs_confirmation`.
- [x] T014 `tests/fixtures/case_ledger_stages.py` — example stage names; assert `twinbox_core/` contains none of them.

## Durability

- [x] T015 Wire ledger-derived `closed` into `classification_store` lifecycle projections.
- [x] T016 Fold `closed` into the nightly full-window compaction so a once-closed case stays closed across full rewrites.

## Open

- [x] T017 MCP exposure of ledger append / current-view queries.

## Verification

`python3 -m unittest tests.test_case_ledger tests.test_value_ranking tests.test_queue_visibility tests.test_extract -q`
