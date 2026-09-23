# Implementation Plan: Append-only Case Lifecycle Ledger

**Feature**: `015-case-lifecycle`

**Scope**: R4 ledger slice only. This plan covers the pure append/current-view/derive engine plus its unit tests. It deliberately does **not** touch `classification_store.py`, the nightly full-window compaction, MCP tool names, R1 reopen semantics, R2 extract source, or R3 score defaults.

## File layout

```
twinbox_core/
└── case_ledger.py          # NEW — append-only ledger + current view + derived states

tests/
├── test_case_ledger.py     # NEW — unit tests for the ledger slice
└── fixtures/
    └── case_ledger_stages.py  # NEW — example business stage names (fixtures only), used to
                                # assert twinbox_core/ contains none of them
```

## `twinbox_core/case_ledger.py`

| Symbol | Kind | Responsibility |
| --- | --- | --- |
| `LedgerError` | exception | Stable, non-sensitive rejection reason. |
| `DEFAULT_ATTRIBUTE` | const | `"lifecycle_state"`. |
| `DEFAULT_STATES` | const | `("open", "waiting_on_me", "waiting_on_others", "closed")`. |
| `REOPEN_STATES` | const | `("open",)` — values that legally reopen a `closed` case. |
| `STATUS_VALID` / `STATUS_NEEDS_CONFIRMATION` | const | Line `status` values. |
| `case_ledger_path(state_root)` | fn | `runtime/context/case-ledger.jsonl`. |
| `case_ref(scope_id, case_key)` | fn | Reuse `classification_store.case_ref` for stable identity. |
| `load_records(state_root)` | fn | Parse every JSON line in order; raise `LedgerError` on corrupt/partial line. |
| `append_record(...)` | fn | Validate value against declared states, decide `status` vs current view, append one line (locked + fsync), never rewrite old lines. |
| `current_view(state_root)` | fn | `{(case_ref, attribute): latest-valid_by_valid_from}`; skips `needs_confirmation`; ignores backfill. |
| `derive_case_states(state_root, *, scope_id, attribute)` | fn | Read analysis rows (phase-4 YAML) + envelope dates; emit candidate records with `source="analysis_derived"`. |
| `sync_derived_states(state_root, *, scope_id, attribute)` | fn | Append only when derived value differs from current value. |
| `drop_closed_from_attention(payload, state_root, ...)` | fn | Remove `closed` threads from pulse `needs_attention`; keep `thread_index`. |
| `legal_states(state_root)` / `reopen_states(state_root)` | fn | Resolve declared state set from pack `lifecycles` (optional), else the four defaults. |

### Data invariants

1. **Append-only.** Every write opens the file in `a` mode under an exclusive `fcntl` lock and appends exactly one `json.dumps(...) + "\n"`; no read-modify-write of the whole file.
2. **Line shape.** `{case_ref, attribute, value, valid_from, recorded_at, evidence_ref, source, status}` plus optional `stage_proposals` / `followup`.
3. **Current view.** Per `(case_ref, attribute)`, pick the record with the largest `(valid_from, recorded_at)`; skip `status=needs_confirmation`; a backfill (`valid_from` older than current) therefore never wins.
4. **Transitions.** `value not in legal_states` → `needs_confirmation`. Previous current value `closed` and new value not in `reopen_states` → `needs_confirmation`. Otherwise `valid`.
5. **Derivation.** Over existing analysis rows only: `resolved_by_reply` ⇒ `closed`; pending row with `waiting_on_me` ⇒ `waiting_on_me`; a wait targeted at a third party ⇒ `waiting_on_others`; else `open`. `valid_from` = latest envelope date for the thread; `evidence_ref` = latest message ref. No LLM; no system-prompt edit.

### Pulse integration

`pulse.build_activity_pulse` calls `drop_closed_from_attention(payload, state_root)` after building the payload and before projection attachment, wrapped in a fail-open `try/except` that records `case_ledger_error` in `diagnostics` (mirrors the existing `projection_error` pattern). With no ledger file, this is a no-op, so existing flow is unchanged.

## Out of scope (open tasks)

- Wire ledger-derived `closed` into `classification_store` lifecycle projections.
- Fold `closed` into the nightly full-window compaction so a once-closed case stays closed across full rewrites.
- MCP exposure of ledger append/current-view queries.

## Verification

`python3 -m unittest tests.test_case_ledger tests.test_value_ranking tests.test_queue_visibility tests.test_extract -q` — all green.
