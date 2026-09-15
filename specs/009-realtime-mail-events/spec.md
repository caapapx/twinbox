# Feature Specification: Realtime Mail Events

**Feature Directory**: `009-realtime-mail-events`

**Created**: 2026-09-15

**Status**: Planned（Phase 3 of enterprise roadmap; after Phase 1 read plane）

**Related**: constitution I–II; `007-local-scheduler`; IDLE must only trigger `quick-refresh`.

## Purpose

Realtime ingress (IMAP IDLE / provider push / poll fallback) that refreshes local pulse without putting LLM on the query path. UIDVALIDITY baselines; untrusted mail ingress guards.

## Requirements

- **FR-001**: IDLE/push success runs **only** `quick-refresh` (fetch + pulse; no LLM).
- **FR-002**: Daytime/nightly analysis remains cron or explicit `twinbox_sync`.
- **FR-003**: UIDVALIDITY change / first baseline / duplicate notify must not mark old mail as new.
- **FR-004**: Subject/body/attachment names/display names are untrusted; never used as tool authorization.
- **FR-005**: External supervisor launches IDLE worker; do **not** revive OpenClaw daemon; do **not** rewrite `schedule run-due`.
- **FR-006**: `twinbox_latest_mail` MUST remain non-blocking for IMAP while IDLE runs.

## Non-Goals

- Per-message LLM wakeups
- Replacing cron with IDLE-only analysis

## Success Criteria

- Disconnect recovery + UIDVALIDITY fixtures pass
- Query tools still read local pulse only
