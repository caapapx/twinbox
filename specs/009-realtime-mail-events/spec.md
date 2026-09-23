# Feature Specification: Realtime Mail Events

**Feature Directory**: `009-realtime-mail-events`

**Created**: 2026-09-15
**Status**: Local implementation and fixture verification complete; runtime deployment is not authorized or verified.
**Related**: constitution I–II; `007-local-scheduler`; [plan](plan.md). IDLE must only trigger `quick-refresh`.

## Purpose

Provide an externally supervised IMAP IDLE / bounded-poll ingress hint that refreshes
the local pulse without putting LLM analysis on the notification path. It protects
first baselines and UIDVALIDITY resets from becoming false “new mail” business
signals, while treating all mailbox-provided text as untrusted input.

## Requirements

- **FR-001**: An accepted IDLE/poll notification invokes **only** `quick-refresh`
  (fetch + local pulse; no LLM). The notification source cannot choose another job.
- **FR-002**: Daytime/nightly analysis remains cron or explicit `twinbox_sync`.
- **FR-003**: First baseline, duplicate notification, and UIDVALIDITY reset must not
  label historic/rebuilt mail as a new business item.
- **FR-004**: Subject/body/attachment names/display names and arbitrary server text
  are untrusted; none can become tool authorization, a command, or an execution
  parameter.
- **FR-005**: An external supervisor may launch the foreground worker. TwinBox must
  not revive an OpenClaw daemon or rewrite `schedule run-due`.
- **FR-006**: `twinbox_latest_mail` remains non-blocking for IMAP while a watcher runs
  because it reads local pulse state only.

## Non-Goals

- Per-message LLM wakeups
- Replacing cron or explicit sync with IDLE-only analysis
- Installing a production process-manager unit or contacting a real mailbox without
  explicit authorization

## Success Criteria

- Fixture tests prove disconnect recovery, strict trigger parsing, UIDVALIDITY safety,
  poll fallback, and that notifications can only request `quick-refresh`.
- Query tools continue to read local pulse without making an IMAP connection.
- A separately authorized runtime smoke must prove the same properties before this
  feature is described as deployed.
