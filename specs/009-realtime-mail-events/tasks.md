# Tasks: Realtime Mail Events

**Status**: Local code + fixture verification complete; runtime installation and real-mailbox smoke remain pending explicit authorization.

## Completed locally (2026-09-20)

- [x] T001 Add a foreground IDLE worker entry suitable for an external supervisor;
  do not revive an OpenClaw daemon.
- [x] T002 On strictly recognized EXISTS/RECENT notifications, request only
  `sync --job quick-refresh --account-id …`.
- [x] T003 Preserve first-baseline and UIDVALIDITY-reset watermarks so historic or
  rebuilt messages are not emitted as new business mail.
- [x] T004 Fall back to bounded polling when IDLE is unsupported.
- [x] T005 Reject untrusted ingress as command/authorization data; arbitrary server
  text is not a trigger and is not reflected in output.
- [x] T006 Add fixtures for disconnect recovery, reset safety, poll fallback, and the
  invariant that `latest-mail` reads local pulse rather than waiting on IMAP.

## Pending runtime gate

- [ ] T007 After explicit mailbox and operations approval, install an **external**
  foreground-process supervisor and run a read-only, non-delivery smoke. Verify a
  real notification only performs `quick-refresh`, does not invoke analysis, and
  does not block `latest-mail`. Record the environment and evidence without storing
  mailbox content or credentials in this repository.
