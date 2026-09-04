# Verification: As-Built MCP Baseline

**Date**: 2026-09-04  
**Branch**: `master`  
**Method**: code inspection + tracked tests（不依赖真实 IMAP）

## Commands / Artifacts Checked

| Check | Result |
| --- | --- |
| `mcp-server.mjs` tool registration | Exactly nine `twinbox_*` tools |
| `tests/mcp-smoke.mjs` | Asserts the same nine-tool surface |
| IMAP select paths in `imap_fetch.py` | Uses `readonly=True` |
| Queue mutations | Only `runtime/context/user-queue-state.yaml` |
| Analysis outputs | `daily_urgent`, `pending_replies`, `sla_risks`, `weekly_brief` |
| Config model | Singular `mailbox` in `config.py` |
| `config/extract-profiles.yaml` | `weekly_report` query preset only |
| `config/schedules.yaml` | Present; no in-repo executor for listed jobs |
| Planned modules `adapter.py` / `events.py` / `vault.py` | Absent |
| Credential write path | `setup_from_env` stores `mailbox.imap.password` plaintext in local JSON |

## Classification Snapshot

- **Implemented**: single-mailbox read-only MCP/CLI + local queue + extract.
- **Not implemented**: anything under `specs/001` beyond documentation; all `002` tasks unchecked.
- **Do not claim**: org-tree weekly compliance, auto-forward, chat webhook confirmation, encrypted vault as current behavior.
