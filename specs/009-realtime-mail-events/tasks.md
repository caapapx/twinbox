# Tasks: Realtime Mail Events

**Status**: Planned (implement after Phase 1 gate)

- [ ] T001 IDLE worker entry under external supervisor (no OpenClaw daemon)
- [ ] T002 On EXISTS/RECENT → `sync --job quick-refresh --account-id …`
- [ ] T003 UIDVALIDITY baseline + reset watermarks safely
- [ ] T004 Poll fallback when IDLE unsupported
- [ ] T005 Ingress guard: treat headers/bodies as untrusted
- [ ] T006 Tests: disconnect recovery; latest-mail never blocks on IDLE
