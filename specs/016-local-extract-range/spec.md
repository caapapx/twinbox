# Feature Specification: Local extract range

**Feature Directory**: `specs/016-local-extract-range`

**Created**: 2026-09-23

**Status**: Draft (thin contract)

**Type**: `feature`

**Input**: Historical range queries always hit IMAP even when envelopes for that window already sit on disk; empty extract still looks like success; weekday filters from `weekly_report` must not become a silent default for every date query.

## What / Why

Owners ask for mail in a past window (e.g. last week's weekly reports). Within the retained local window, Twinbox should answer from disk without IMAP. Beyond retention, fall back to IMAP. The tool name stays `twinbox_extract`.

## User-visible behavior

1. `twinbox_extract` accepts `source`: `auto` (default), `local`, or `imap`.
2. `auto`: if `since` is on or after the oldest local envelope date for the requested folders, read local retention and do not call IMAP; otherwise use IMAP as today.
3. `local`: always read local retention; never call IMAP. Bodies come only from `phase1-context` `sampled_bodies` when present; otherwise body is empty.
4. `imap`: always use the current IMAP path.
5. Empty local store is outside retention for `auto`.
6. `until` stays exclusive. Existing result fields stay; responses add `source_used` (`local` or `imap`). Zero matches still set `result: "no_match"` with `ok: true`.
7. `weekdays` remains a content filter. Only the `weekly_report` profile sets fri/sat/sun by default. A date-range query with no profile and no `weekdays` argument does not filter by weekday.
8. IMAP recall for `twinbox_extract` is the date window (`SINCE` / exclusive `BEFORE`). `subject_contains` and `subject_regex` are applied locally after headers are retrieved.
9. Server `HEADER Subject` search is not a recall path. Coremail often returns zero UIDs for CJK subjects even when matching mail exists in the window. A caller that still passes subject terms to the IMAP helper must fall back to the same date window when that search is empty or fails, without widening `until`.

## Acceptance

- In-retention `auto` does not call IMAP and returns `source_used=local`.
- `source=local` outside retention still does not call IMAP.
- `source=imap` calls IMAP.
- No profile and no weekdays argument leaves `weekdays` unset.
- `weekly_report` still carries fri/sat/sun.
- Zero matches include `result=no_match` and `ok=true`.
- `subject_contains` on an IMAP extract does not narrow the IMAP UID search; local matching keeps only subjects that contain the term.
- An empty IMAP `HEADER Subject` result falls back to the date window and does not drop candidates before local filtering.

## Boundaries

- No new MCP tool names. No pulse refresh. No SMTP / IMAP STORE.
- Does not invent bodies that were never sampled.
- Does not change R1 reopen rules or pulse scoring.
- Does not treat a server subject search as sufficient recall for CJK mail.
