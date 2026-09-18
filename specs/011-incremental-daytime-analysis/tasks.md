# Tasks: Incremental daytime analysis

- [x] T001 Thin spec (this directory)
- [x] T002 `cmd_sync` daytime: no new mail + YAML → skip LLM; nightly-full / missing YAML → full
- [x] T003 `run_analysis(..., only_ids=)` merge YAML by thread_key; do not rewrite weekly on patch
- [x] T004 Tests: noop skip; one new envelope keeps old urgent; nightly still full
- [x] T005 `last-run.analysis_path` + daytime incremental `only_ids` unit test
- [x] T006 Fix R8: `new_count>0` + empty `new_ids` → skip not full; fetch returns `new_envelope_ids`
- [x] T007 Pending analysis ids: quick-refresh enqueue; daytime consumes leftover after fetch noop; failure/budget/UIDVALIDITY/FLAGS-only/account isolation (`tests/test_quick_refresh.py`)
- [x] T008 Lookback 7→30 SINCE backfill; UIDVALIDITY mismatch refetches; extract passes account_id (`tests/test_imap_fetch.py`, `tests/test_extract.py`)
