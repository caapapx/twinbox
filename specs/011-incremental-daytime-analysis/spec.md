# Feature Specification: Incremental daytime analysis

**Feature Directory**: `specs/011-incremental-daytime-analysis`

**Created**: 2026-09-16

**Status**: Draft (thin contract)

**Type**: `feature`

**Input**: Daytime-sync currently rewrites the whole lookback window with one LLM call even when IMAP fetch is `noop`. Nightly-full remains the full rebuild.

## What / Why

Mailbox owners pay 80–150s of analysis on every `daytime-sync`, including hours with no new mail. IMAP is already incremental (`new_envelope_count` / `noop`). Analysis must skip or patch instead of covering YAML every time.

## User-visible behavior

1. `daytime-sync` with no new envelopes and existing analysis YAML skips LLM, rebuilds pulse from last analysis (`analysis.skipped`, reason `no-new-mail`). Query tools still read pulse; FR-006 stale-on-read is unchanged.
2. `daytime-sync` with new envelopes, or with leftover pending analysis ids (e.g. after `quick-refresh`), sends those threads to the LLM, then merges urgent/pending/sla by `thread_key`. Threads that left the lookback window drop out of the YAML and the pending set.
3. `nightly-full` always rewrites the whole window (SLA / missed tags). Missing YAML → full analysis. Successful analysis only acks envelope ids that actually reached the LLM; budget leftovers stay pending.
4. `quick-refresh` still skips LLM. New IMAP envelopes are enqueued for later daytime/nightly consumption. FLAGS-only updates do not enqueue.

## Acceptance

- Constructed two-step sync: second fetch `new_envelope_count=0` does not call `call_llm`.
- `quick-refresh` then daytime fetch `noop`: the quick-refresh envelopes are still analyzed (pending ids, not fetch-diff).
- Second fetch with one new envelope: prompt subjects are only that thread; previous urgent rows for other keys remain.
- `nightly-full` still calls LLM with the full selected window.
- `cmd_sync` / `last-run.json` record `analysis_path` ∈ {skip, incremental, full, quick} so L2 对照不用猜路径。
- IMAP `new_envelope_count>0` but no new ids in the lookback window (duplicate UID / trimmed) → **skip** (`no-new-ids-in-window`), never full.
- LLM/parse failure keeps pending ids; select budget leftovers are not batch-acked.
- UIDVALIDITY change drops pending ids for that folder.
- `latest_mail` / `todo` on a stale pulse still do not IMAP (002 FR-006).

## Boundaries

- No new MCP tools. No TTL-triggered reanalysis on read.
- Pack `threshold_*` stay on `semantic_band`, not select.
- Daytime does not re-score threads with no new mail (ceiling; nightly repairs). `ponytail:` in code.
- `extract_events` may refresh from the full current envelope window (no LLM). Weekly brief file is not overwritten by a daytime patch.
