# Implementation Plan: Realtime Mail Events

**Feature Directory**: `009-realtime-mail-events`
**Status**: Local implementation and fixture verification complete; no production supervisor or mailbox runtime has been installed.
**Date**: 2026-09-20

## Goal and boundary

Provide an externally supervised, read-only IMAP notification worker that asks the
existing `quick-refresh` path to update the local pulse. It is an ingress hint, not
an analysis scheduler: notification events must never invoke an LLM, change IMAP
state, send mail, or execute data carried by the mailbox.

The implementation adds the `twinbox realtime-watch` foreground CLI command and
`RealtimeMailWorker`. A process manager may run that foreground command later, but
TwinBox neither daemonizes itself nor creates/edits a process-manager unit in this
change.

## Design

1. **Connection and lifecycle**
   - The external supervisor starts `twinbox realtime-watch`; the worker has no
     daemon lifecycle and does not alter `schedule run-due`.
   - It selects the configured folders read-only and maintains a bounded IDLE
     session. Disconnects recover with a bounded backoff. A server that rejects
     IDLE switches to bounded polling.

2. **Strict event boundary**
   - The only accepted IMAP notification grammar is exactly
     `* <decimal> EXISTS` or `* <decimal> RECENT`.
   - Any accepted notification calls only `cmd_sync("quick-refresh", account_id=…)`.
     The worker does not select a sync job from server text and does not call
     daytime/nightly analysis.
   - All other server lines, mail headers, subjects, bodies, attachment names, and
     display names are untrusted data. They are neither commands nor authorization
     inputs and are not reflected in worker status output.

3. **Watermarks and reset safety**
   - The first observed UIDVALIDITY records the current maximum UID as a baseline
     and emits no refresh, preventing a historic mailbox replay.
   - On UIDVALIDITY change, the worker deliberately leaves the old watermark for
     `fetch_incremental()` to invalidate and rebuild. The fetch result labels reset
     folders and suppresses their rebuilt envelopes from `new_envelope_ids`, so a
     UID namespace reset cannot become a new business event.

4. **Read-plane isolation**
   - `latest-mail` continues reading the local pulse only. The watch worker has no
     code path that makes query tools wait for its socket or its refresh result.

## Verification

Local fixture coverage proves the event-to-refresh boundary, initial baselining,
UIDVALIDITY reset handling, polling fallback, hostile server-line rejection,
disconnect recovery, CLI foreground entry, and the local-pulse read boundary.

Runtime verification remains deliberately separate: it requires explicit approval
for a real mailbox and a selected external supervisor. It must be a read-only,
non-delivery smoke test and must prove that a real notification updates only the
local pulse without starting analysis.

## Rollback

Do not launch `realtime-watch` (or remove the external supervisor unit once one is
explicitly approved). Existing cron and explicit `twinbox sync` behavior are
unchanged; no persisted schema migration or mailbox mutation is required.
