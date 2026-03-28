# twinbox ROADMAP

**Last updated:** 2026-03-29  

This file **replaces** scattered plan artifacts that lived in-repo (now removed): `skill-creator-plan.md`, `.cursor/plans/prompt_and_code_optimization_*.plan.md`, `docs/superpowers/plans/*`, `docs/superpowers/specs/*` (incremental-mail design), `docs/core-refactor-v1.md`, and the empty `docs/core-refactor-v2-latest.md` placeholder.  

**Current facts** for daemon, Go shim, vendor, and modular sim: [`docs/ref/daemon-and-runtime-slice.md`](docs/ref/daemon-and-runtime-slice.md). **Architecture:** [`docs/ref/architecture.md`](docs/ref/architecture.md). **CLI:** [`docs/ref/cli.md`](docs/ref/cli.md). **OpenClaw host:** [`openclaw-skill/DEPLOY.md`](openclaw-skill/DEPLOY.md).

---

## Sources merged into this roadmap

| Former artifact | Role |
|-----------------|------|
| `skill-creator-plan.md` | Track A (local agent) vs Track B (OpenClaw) packaging, verification ladder, platform gaps |
| `.cursor/plans/prompt_and_code_optimization_*.plan.md` | Phase 2–4 prompt architecture + Phase 4 correctness (loading, recipient_role, dry-run, calibration) |
| `docs/superpowers/plans/2026-03-26-incremental-mail-processing-implementation.md` | UID watermark daytime sync, merge context, queue state, orchestration wiring |
| `docs/core-refactor-v1.md` | Phased core refactor (paths → LLM boundary → context → skill surface → Go reassessment) + explicit TODO-1…4 |
| `git log` on `dev-go` (recent ~80 commits) | Onboarding v2, single `twinbox.json`, OpenClaw deploy decomposition, daemon/RPC, vendor, tests |

---

## Done (verified in tree or closed plans)

### Commits (themes, 2026-03)

- **Phase 4 / prompts:** loading fixes, `recipient_role` scoring vs display split, truthful `--dry-run`, calibration + onboarding notes into context (`024ea99` and related).
- **Onboarding / config:** OpenClaw journey shell, LLM import from OpenClaw, single config source, TTY/journey polish, secret masking.
- **OpenClaw deploy:** step modules, JSON merge helpers, deploy tests, Himalaya bundling, canonical `SKILL.md` under state root, symlink to OpenClaw skills dir.
- **Runtime:** JSON-RPC daemon + protocol tests, injectable CLI runner for `cli_invoke`, vendor install/status/integrity, `twinbox-go` HTTP archive install, profile + `TWINBOX_HOME` vendor sharing.
- **Orchestration:** loading phase1/4 orchestration in Python; lazy imports in `task_cli` for faster daemon subprocesses.
- **Incremental mail (plan closure):** `imap_incremental`, `merge_context`, `user_queue_state`, daytime-sync path, queue dismiss/complete/restore + tests — per implementation plan status (2026-03-26).

### Cursor plan: prompt + code optimization

All items were marked **completed** in plan frontmatter: Phase 4 `onboarding_profile_notes` loading, `recipient_role` fix, dry-run after `skip_phase4` filter, `instance-calibration-notes.md` bridge, `prompt_fragments` + system/user split for Phase 2/3/4, tests + SKILL updates (landed with `024ea99`).

### Core refactor (high level)

- **Paths / roots:** Python `paths.py`, config files under `~/.config/twinbox/`, documented in [`docs/ref/code-root-developer.md`](docs/ref/code-root-developer.md).
- **Orchestration contract:** `twinbox_core.orchestration` as shared contract + `twinbox-orchestrate` entrypoint.
- **Loading:** Phase 2/3 context building and much loading logic in Python (not duplicated shell-heavy paths for new work).
- **LLM module:** `src/twinbox_core/llm.py` exists; full “single boundary for all phase thinking transports” remains an incremental goal (see backlog).
- **Daemon + Go thin client + vendor:** shipped; see daemon slice doc.

---

## Not done / open backlog

Grouped for execution; overlaps README “Current Focus” where noted.

### P0 — product contracts

| Item | Notes |
|------|--------|
| **`context_updated` → real rerun** | Emit marker or event after `context import-material` / `upsert-fact` / profile updates; `context refresh` should trigger Phase 1 (or scoped rerun), not only print hints. (ex-TODO-2) |
| **Review / action CLI** | `twinbox review approve|reject`, `twinbox action apply` with explicit confirmation. (ex-TODO-3) |
| **Skill surface vs phase jargon** | Task-facing CLI is broad; SKILL should stay thin and avoid requiring readers to understand phase numbers for happy paths. (ex-TODO-1 remainder) |

### P1 — OpenClaw / Track B (platform + host)

| Item | Notes |
|------|--------|
| **`preflightCommand` auto-exec** | Verify whether OpenClaw runs it automatically; document actual behavior. |
| **`metadata.openclaw.schedules`** | Treat as declarative until platform import is proven; validate against real cron/system-event behavior. |
| **`twinbox` agent session isolation** | Reduce `agent:twinbox:main` reuse / empty assistant content; align with “new session after skill/env change”. |
| **Host hardening** | Production service install, retry, alerting, stale-artifact fallback ownership. |
| **Subscription registry** | Multi-channel delivery beyond ad-hoc session history. |
| **Track A polish** | `.claude/skills/twinbox` vs root `SKILL.md` boundaries, references depth, eval parity with hosted smoke. |

### P2 — engineering quality

| Item | Notes |
|------|--------|
| **Unified LLM boundary** | Concentrate provider differences, retry, timeout, JSON repair for all phase thinking paths (beyond current `llm.py` usage). |
| **Render / merge dedup** | Less duplication between merge-only and parallel Phase 4 paths where still split. |
| **Attention-budget–driven deps** | Stronger tests around `attention-budget.yaml` as phase gate vs “file exists” only. |
| **Eval / baseline** | `twinbox-eval-phase4` and baselines: repo policy is **local `pytest`** (no GitHub Actions in-tree); optional external CI is a host choice. (ex-TODO-4, reframed) |

### P3 — automation (read-only stance until gates exist)

| Item | Notes |
|------|--------|
| **Draft generation + approval** | Behind explicit gates; Phases 1–4 stay read-only. |
| **Structured audit trail** | e.g. `runtime/audit/` narrative from README. |
| **Action template registry + review UI/CLI** | Contract-first pieces exist in docs; product surfaces still open. |
| **Runtime archive snapshots** | Nightly/weekly/failure snapshots for artifacts. |
| **Fully local LLM** | Optional deployment mode; not blocking hosted OpenAI-compatible path. |

---

## Incremental mail design note

The **design spec** for UID watermark + user queue state was under `docs/superpowers/specs/` (removed with this consolidation); behavior is **implemented** (see Done). Recover old narrative from git history if needed.

---

## How to update this file

- After a **shippable** slice lands, move bullets from **Not done** → **Done** (or delete) and add a one-line pointer to the merge commit if useful.
- Prefer linking **reference docs** for deep design; keep this file a **single backlog index**.
