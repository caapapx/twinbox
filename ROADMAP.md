# twinbox Roadmap

**Last Updated:** 2026-04-01

---

## Overview

twinbox 是以线程为中心的邮件 Copilot 基础设施。核心路径：read-only → draft → controlled send。

本路线图基于 commit 记录维护，按业界通用格式组织：已完成功能、进行中工作、计划功能。

---

## Completed (已完成)

### Q1 2026 (March - April)

#### Core Infrastructure

**Runtime & Daemon**
- JSON-RPC daemon + protocol tests (`2026-03-29`)
- Go thin client as standalone entrypoint (`twinbox-go` → `twinbox`) (`2026-03-29`)
- Lazy daemon start on RPC dial failure (`2026-03-30`)
- Supervised daemon with restart capability (`2026-03-29`)
- Vendor tarball installation (`twinbox install --archive`, `twinbox vendor install|status|integrity`) (`2026-03-30`)
- Shared vendor via `--profile` + `TWINBOX_HOME` (`2026-03-29`)
- Runtime verification script (`scripts/verify_runtime_slice.sh`) (`2026-03-29`)

**Configuration & Onboarding**
- Primary config file `twinbox.json` with IMAP UTF-7 support (`2026-03-30`)
- OpenClaw onboarding flow with TTY interaction (`2026-03-30` - `2026-04-01`)
  - Bootstrap and push binding handoff (`2026-04-01`)
  - TTY push session picker and digest cron presets (`2026-04-01`)
  - TTY routing rules and push after deploy (`2026-04-01`)
  - Context bundle paste and `import-material --stdin` (`2026-03-31`)
- Mailbox auto-login reset on email change (`2026-03-30`)
- Merged mailbox env for immediate validation (`2026-03-30`)

**OpenClaw Integration**
- Vendor-safe OpenClaw bridge with cadence push (`2026-03-29`)
- OpenClaw plugin bundled in vendor tarball (`2026-03-30`)
- Bundled dist without npm requirement on hosts (`2026-03-30`)
- OpenClaw skill moved to `integrations/openclaw` (`2026-03-30`)
- Onboarding tools: `twinbox_push_confirm_onboarding`, `twinbox_onboarding_finish_routing_rules`, `twinbox_context_import_material` (`2026-03-30`)
- SKILL.md hardened advance rules for profile setup and routing (`2026-03-30`)

#### Orchestration & Loading

**Python Core Migration**
- Phase 1-4 thinking migrated to Python (`2026-03-20`)
- Phase 2-3 loading converged to shared builder (`2026-03-20`)
- Shared orchestration contract CLI (`task_cli`) (`2026-03-20`)
- Canonical state root extended to Phase 1-3 (`2026-03-20`)
- `task_cli` lazy import for faster daemon subprocess (`2026-03-29`)

**Phase 4 Enhancements**
- Loading fixes, `recipient_role` scoring separation (`2026-03-29`)
- Real `--dry-run` implementation (`2026-03-29`)
- Calibration and onboarding notes in context (`2026-03-29`)
- Shared action candidates across phase4 (`2026-03-29`)
- Configurable CC downweight (`2026-03-29`)

**Context & Profile**
- Unified human context storage (`2026-03-29`)
- Bridge onboarding calibration into loading (`2026-03-29`)

#### Task-Facing CLI

**Core Commands** (`2026-03-23`)
- `queue list/show/explain` - Queue management
- `context import-material/upsert-fact/profile-set/refresh` - Context operations
- `thread inspect/explain` - Thread analysis
- `digest daily/weekly` - Digest generation
- Unified entrypoint `scripts/twinbox` with default `--json` output

**Action & Review** (`2026-03-24`)
- `action suggest/materialize` with ActionCard model
- `review list/show` with ReviewItem model
- DigestView and object contracts

#### Digest & Reporting

- Daily ledger replay into weekly brief (`2026-03-29`)
- Customizable weekly digest template (`2026-03-29`)
- Reference material path for weekly brief (`2026-03-29`)
- Weekly digest snapshot contract (`2026-03-29`)
- Digest text output as markdown (`2026-03-29`)

#### Documentation & Repository

**Docs Restructure** (`2026-03-24`)
- `docs/README.md` as single entry point
- New structure: `architecture/`, `roadmap/`, `archive/`
- `architecture.md` moved to `docs/ref/`
- Root entry convergence: README, AGENTS.md, CLAUDE.md point to `docs/`
- Validation contract at `docs/ref/validation.md` (local-only, not tracked)

**Recent Updates** (`2026-03-31` - `2026-04-01`)
- Apache-2.0 relicense with LICENSE and NOTICE (`2026-04-01`)
- Removed docs/assets, docs/openclaw, docs/superpowers (`2026-04-01`)
- Removed beta case study and sensitive references (`2026-04-01`)
- Added BUGFIX.md for bug narratives (`2026-03-31`)
- Case study moved to how-to-make-twinbox (`2026-03-31`)

#### Testing & Quality

- `test_task_cli.py` covering CLI and view models (`2026-03-23`)
- Runtime verification script for daemon/vendor/loading/OpenClaw/Go (`2026-03-29`)

#### Bug Fixes

**March 2026**
- Surface onboard errors when OpenClaw CLI missing (`2026-03-31`)
- Parse vendor tarball version without tomllib (Python <3.11) (`2026-03-30`)
- Structured JSON recovery on missing pulse/thread (`2026-03-30`)
- Start daemon in `run_openclaw_deploy` (`2026-03-30`)
- Ignore stale fragment_path in twinbox.json (`2026-03-30`)
- Resolve code root to repo root when cwd under cmd/twinbox-go (`2026-03-30`)
- Explain skipped tools-fragment prompt when file missing (`2026-03-30`)
- Reset auto mailbox login on email change (`2026-03-30`)
- Use merged mailbox env for immediate validation (`2026-03-30`)

#### Earlier Milestones (March 2026)

**LLM Pipeline**
- Phase 1-4 loading/thinking separation
- Intent classification via LLM
- Dual backend with OpenAI-compatible interface
- JSON output robustness

**Paths & Roots**
- Python `paths.py` with `~/.config/twinbox/` pointer files
- See `docs/ref/code-root-developer.md`

**Incremental Mail** (Design closed)
- `imap_incremental`, `merge_context`, `user_queue_state`
- `daytime-sync` path
- Queue dismiss/complete/restore with tests

---

## In Progress (进行中)

Currently no active development branches.

---

## Planned (计划中)

### P0 - Critical for Production

| Item | Description | Status |
|------|-------------|--------|
| **多邮箱支持** | Multi-mailbox support for handling multiple email accounts | Not Started |
| **IMAP 接入模块重构** | Replace Himalaya CLI with new IMAP integration module | Not Started |
| **心跳机制改造** | Adapt Categraf-like heartbeat mechanism for improved push stability and performance | Not Started |
| **Context refresh triggers Phase 1 rerun** | `context import-material`/`upsert-fact`/profile updates should trigger actual Phase 1 rerun, not just prompt | Planned |
| **Review/Action CLI completion** | `twinbox review approve <id>`, `twinbox action execute <id>` | Planned |

### P1 - OpenClaw & Host Integration

| Item | Description | Status |
|------|-------------|--------|
| **preflightCommand auto-execution** | Verify and document OpenClaw's automatic execution behavior | Planned |
| **metadata.openclaw.schedules verification** | Validate against real cron/system-event behavior | Planned |
| **Agent session isolation** | Reduce `agent:twinbox:main` reuse; align with skill/env change → new session | Planned |
| **Host hardening** | Production-grade service install, retry, alerting, stale-artifact fallback | Planned |
| **Subscription registry** | Multi-channel delivery without relying on temporary session history | Planned |
| **Track A polish** | `.claude/skills/twinbox` vs root `SKILL.md` boundary, references depth, eval alignment | Planned |

### P2 - Engineering Quality

| Item | Description | Status |
|------|-------------|--------|
| **Unified LLM boundary** | Centralize provider differences, retry, timeout, JSON repair across all phases | Planned |
| **Render/merge deduplication** | Reduce duplication in merge-only and parallel Phase 4 paths | Planned |
| **Attention-budget driven dependencies** | Strengthen phase gate tests using `attention-budget.yaml`, not just file existence | Planned |
| **Eval/baseline** | Local `pytest` for `twinbox-eval-phase4` and baseline (no GitHub Actions in repo) | Planned |

### P3 - Automation (Phase 1-4 remain read-only until gates in place)

| Item | Description | Status |
|------|-------------|--------|
| **Draft + approval** | Explicit gates before send; Phase 1-4 stay read-only | Planned |
| **Structured audit trail** | `runtime/audit/` narrative as described in README | Planned |
| **Action template registry + review UI/CLI** | Contract exists in docs; product surface open | Planned |
| **Runtime archive snapshots** | Nightly/weekly/on-failure artifact snapshots | Planned |
| **Fully local LLM** | Optional deployment mode; doesn't block OpenAI-compatible hosted path | Planned |

---

## Release Gates (发布门槛)

Before next release, these must be validated:

- [ ] **OpenClaw host full flow manual test** - Clean host walkthrough via `twinbox onboard openclaw --json`
- [ ] **Host scripted alternative path** - `twinbox deploy openclaw --json`, `--rollback --json`, upgrade + redeploy loop
- [ ] **Vendor/no-clone delivery path** - Verify `twinbox install --archive` or `twinbox vendor install` works without full repo checkout
- [ ] **Daemon/CLI real host smoke test** - `twinbox daemon start/status/stop`, `twinbox task todo/weekly --json` on real host
- [ ] **Platform behavior verification** - If committing OpenClaw auto-capability, verify `preflightCommand` and `metadata.openclaw.schedules` actual consumption

---

## Maintenance Guidelines (维护指南)

### How to Update This Roadmap

1. **After each deliverable merge**: Move item from Planned → Completed with commit reference and date
2. **Deep design**: Link to reference docs; keep this file as single backlog index
3. **Sync with README**: Root README/README.zh "Current Focus" should sync with P0-P3 (date + categorization); long tables only maintained here
4. **Release window**: Prioritize "Release Gates" section; only non-blocking items go to P0-P3 long-term backlog

### Commit Message Format

Use conventional commits: `type: short description`

Examples:
- `feat: add multi-mailbox support`
- `fix: resolve IMAP connection timeout`
- `docs: update architecture diagram`
- `refactor: simplify heartbeat mechanism`
- `test: add integration tests for daemon`

### Branch Strategy

- Main branch: `master`
- Feature branches: independent (e.g., `dev-go`), delete after merge
- Merge commits should reference related issues/PRs

---

## References

- Architecture: `docs/ref/architecture.md`
- Current implementation slice: `docs/ref/daemon-and-runtime-slice.md`
- CLI reference: `docs/ref/cli.md`
- Bug fixes: `BUGFIX.md`
- Full documentation: `docs/README.md`


