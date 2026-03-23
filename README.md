# twinbox 📮

[English](./README.md) | [中文](./README.zh.md)

An OpenClaw-native, thread-centric email copilot: understand thread state first, then unlock automation step by step.

Status as of `2026-03-23`: this repository is in an implementation-heavy, read-only-first stage. It already has a shared Python core for Phase 1-4, a stable orchestration contract CLI, and an initial Phase 4 evaluation gate (`twinbox-eval-phase4`). It is not yet a full production runtime with listener/action services.

## What This Is

`twinbox` is not a generic auto-send mail bot and not a polished inbox client demo.

It is a self-hostable foundation for building an email copilot with these traits:

- starts with read-only mailbox onboarding
- reconstructs workflow state from threads instead of single messages
- ingests user-supplied context such as work materials and recurring habits
- turns mailbox state into visible queues like `daily-urgent` and `pending-replies`
- only promotes actions gradually: read-only -> draft -> controlled send

What's already here:

- shell-based mailbox validation and sampling scripts
- a shared Python core for Phase 1-4 loading/thinking and rendering
- a shared orchestration contract (`scripts/twinbox_orchestrate.sh`)
- a Phase 4 accuracy/regression evaluation entrypoint (`twinbox-eval-phase4`)
- context-ingestion support for user-provided materials, habits, and confirmed facts

## Why This Exists

Most email-agent demos optimize for message events, fast automation, and UI interaction.

This project is tuned for a different set of goals:

- enterprise-safe rollout
- thread-centric workflow understanding
- human-in-the-loop decision making
- OpenClaw-native self-hosting and scheduling
- gradual adaptation from one real mailbox into a reusable agent workflow

The result should feel less like "AI reads one email" and more like "AI becomes a usable mailbox copilot for how this person actually works".

## Current Progress

Current release posture: `spec-first`, `shell-first`, `read-only-first`.

What is already in the repository:

- IMAP/SMTP environment checks and local `himalaya` config rendering
- read-only mailbox smoke test and early validation scripts
- progressive validation docs for persona, lifecycle, and daily value outputs
- architecture docs for thread-centric workflow and human context ingestion
- runtime skeleton for future `listener`, `action`, `template`, and `audit` layers
- Phase 1-4 Loading/Thinking separation (LLM replaces hardcoded inference)
- Gastown multi-agent orchestration integration (formula + sling + witness)
- Phase 4 evaluation gate with baseline regression checks

### Progressive Validation Pipeline

The repository currently implements a four-phase, read-only-first funnel.
Each phase narrows the attention window and hands structured output to the next one.

```mermaid
flowchart LR
    M["Mailbox<br/>envelopes + sampled bodies"]
    C["Human context<br/>materials / habits / confirmed facts"]
    P1["Phase 1<br/>Mailbox census + intent classification"]
    B1["attention-budget v1<br/>noise filtered"]
    P2["Phase 2<br/>Persona + business hypotheses"]
    B2["attention-budget v2<br/>role-relevant threads"]
    P3["Phase 3<br/>Lifecycle modeling"]
    B3["attention-budget v3<br/>modeled threads"]
    P4["Phase 4<br/>Daily value outputs"]
    O["Outputs<br/>daily-urgent / pending-replies / sla-risks / weekly-brief"]

    M --> P1 --> B1 --> P2 --> B2 --> P3 --> B3 --> P4 --> O
    C --> P2
    C --> P3
    C --> P4
```

| Phase | Main job | Typical outputs | Why it exists |
|-------|----------|-----------------|---------------|
| 1 | Read the mailbox at distribution level | `phase1-context.json`, `intent-classification.json`, derived census views | Establish the baseline and remove obvious noise early |
| 2 | Infer who this mailbox belongs to and what work matters | `persona-hypotheses.yaml`, `business-hypotheses.yaml` | Filter threads through role, business, and context relevance |
| 3 | Upgrade from labels to thread-level workflow state | `lifecycle-model.yaml`, `thread-stage-samples.json` | Understand where each thread is in a recurring lifecycle |
| 4 | Produce user-visible value surfaces | `daily-urgent.yaml`, `pending-replies.yaml`, `sla-risks.yaml`, `weekly-brief.md` | Answer the operational question: "what should I look at today?" |

Current contract note:

- the implemented runtime handoff still relies on phase-specific structured artifacts, not a fully wired `attention-budget.yaml`
- treat `attention-budget` as the planned convergence contract, not as an already-enforced runtime dependency
- see [Validation Artifact Contract](docs/specs/validation-artifact-contract.md)

Each phase still follows the same internal split:

- `Loading`: deterministic I/O, sampling, and context-pack building
- `Thinking`: LLM inference with evidence and confidence

```bash
# Single phase
bash scripts/phase1_loading.sh && bash scripts/phase1_thinking.sh

# Shared orchestration CLI
bash scripts/twinbox_orchestrate.sh run

# Inspect the contract a skill or adapter can consume
bash scripts/twinbox_orchestrate.sh contract --format json

# Single phase via orchestration CLI
bash scripts/twinbox_orchestrate.sh run --phase 2

# Backward-compatible wrapper
bash scripts/run_pipeline.sh --phase 2
```

### Common Run/Test Paths

If you just want one concrete path to start with, pick from this table instead of scanning every script first.

| Goal | Recommended command | What it gives you |
|------|---------------------|-------------------|
| Validate mailbox access first | `bash scripts/preflight_mailbox_smoke.sh --headless` | Environment checks, config render, and read-only fetch before Phase 1 |
| See the full pipeline shape | `bash scripts/twinbox_orchestrate.sh run --dry-run` | Prints the Phase 1-4 execution plan without running it |
| Run the full pipeline locally | `bash scripts/twinbox_orchestrate.sh run` | Shared orchestration CLI; Phase 4 uses parallel thinking by default |
| Re-run one phase locally | `bash scripts/twinbox_orchestrate.sh run --phase 2` | Useful for focused debugging or partial reruns |
| Inspect the orchestration contract | `bash scripts/twinbox_orchestrate.sh contract --format json` | Machine-readable phase dependencies and entrypoints for operators or skills |
| Manually test Phase 4 fan-out / merge | `bash scripts/phase4_gastown.sh loading`, then `think-urgent` / `think-sla` / `think-brief` / `merge` | Stepwise debugging for the parallel Phase 4 path |
| Dispatch through Gastown | `gt sling twinbox-phase1 twinbox --create` | End-to-end worker / refinery / witness verification |
| Run Python unit tests | `PYTHONPATH=python/src python3 -m unittest discover -s python/tests -v` | Regression coverage for contracts, phase cores, paths, and rendering |
| Run lightweight smoke checks | `python3 -m compileall python/src` and `bash -n scripts/twinbox_orchestrate.sh scripts/run_pipeline.sh scripts/phase4_gastown.sh` | Fast syntax and import checks before a commit |

For the fuller Gastown and fallback command list, see [gastown-operations.md](docs/guides/gastown-operations.md).

### Where Gastown Fits

Gastown is an orchestration adapter around the pipeline. It does not define mailbox semantics; it packages, dispatches, monitors, and merges phase work around the shared orchestration contract.

```mermaid
flowchart LR
    F["Formula<br/>workflow or convoy"]
    S["gt sling"]
    P["Polecat workers<br/>phase tasks / subtasks"]
    R["Refinery<br/>merge outputs and MRs"]
    W["Witness<br/>health monitoring"]

    F --> S --> P --> R
    W -. monitors .-> P
```

| Gastown concept | Role in twinbox |
|-----------------|-----------------|
| `Formula` | Encodes each phase as a `loading -> thinking` workflow and the full pipeline as a convoy |
| `Sling` | Dispatches a phase formula to a worker |
| `Polecat` | Runs the actual phase work or subtask work |
| `Refinery` | Serializes merge and combines child outputs |
| `Witness` | Detects stalled or zombie workers and keeps execution healthy |
| `Convoy` | Tracks the multi-phase pipeline as one higher-level unit |

Current execution model:

- Phase dependencies stay sequential: `1 -> 2 -> 3 -> 4`
- Parallelism mostly lives inside a phase, not across dependent phases
- Phase 4 is the clearest example: `urgent/pending`, `sla-risks`, and `weekly-brief` can run in parallel and merge at the end
- The stable source of truth for local or future skill-driven execution is `scripts/twinbox_orchestrate.sh`, not the formula files

### Shared State Root

Phase 1-4 now separate `code root` from `state root` so Gastown linked worktrees stop writing isolated artifacts.

- `code root`: the current checkout that provides tracked scripts and formulas
- `state root`: the canonical checkout that provides `.env`, `runtime/context/`, `runtime/validation/`, and `docs/validation/`
- Resolution order: `TWINBOX_CANONICAL_ROOT` -> `~/.config/twinbox/canonical-root` -> current checkout
- Safety rule: in a linked worktree, Phase 1-4 all fail fast if no canonical root is configured

```bash
# Register the canonical state root once from the main checkout
bash scripts/register_canonical_root.sh

# Verify what a worker will use
bash scripts/phase4_gastown.sh roots
```

### Pipeline Checklist

1. Register the canonical root from the main checkout with `bash scripts/register_canonical_root.sh`.
2. Verify the resolved roots with `bash scripts/phase4_gastown.sh roots`.
3. Push `master` before `gt sling` so polecat worktrees see the latest scripts and formulas.
4. Run any phase through its normal script entrypoint; all Phase 1-4 scripts now resolve the same canonical state root.
5. Use `bash scripts/twinbox_orchestrate.sh contract --format json` when a skill or operator needs the explicit pipeline contract.
6. Run Phase 4 through `bash scripts/phase4_gastown.sh <step>` or the corresponding `twinbox-phase4-*` formulas when you need fan-out / merge orchestration.

```bash
# Push local master before slinging so polecat worktrees see the latest scripts
git checkout master
git pull --ff-only origin master
git push origin master

# Sling a single phase to gastown
gt sling twinbox-phase1 twinbox --create

# Inspect the shared orchestration contract or run the local CLI
bash scripts/twinbox_orchestrate.sh contract
bash scripts/twinbox_orchestrate.sh run

# Inspect the formula or run the backward-compatible wrapper
gt formula show twinbox-phase4
bash scripts/run_pipeline.sh
```

See [Gastown Operations Guide](docs/guides/gastown-operations.md) and [Gastown Integration Plan](docs/plans/gastown-integration.md).
For the next-step implementation/runtime refactor direction, see [Core Refactor Plan](docs/plans/core-refactor-plan.md).

Follow-up work is tracked in `bd`, not markdown TODOs:

- `twinbox-d9j`: formalize the full Phase 4 fan-out / merge flow as one reproducible Gastown entrypoint
- `twinbox-5zk`: converge Gastown formulas and future skill adapters onto the shared orchestration contract

Not implemented yet:

- a long-running listener manager
- a production action manager
- WebSocket/frontend interaction surfaces
- auto-send or archive automation by default
- tenant-specific hardcoded business logic

## Key Tradeoffs

1. `Thread over message`  
   Decisions are made on thread context, workflow stage, and evidence, not on isolated message snapshots.
2. `Value before automation`  
   The system must prove read-only value before drafting, and prove draft value before sending.
3. `Context is first-class`  
   User-uploaded materials, recurring habits, and confirmed facts are normalized instead of buried in chat history.
4. `OpenClaw-native operation`  
   The repo is designed to work in OpenClaw-style self-hosted environments and also in manual chat-driven initialization.

## Architecture Diagram (ASCII) 🧭

```text
                                +----------------------+
                                |   User / Operator    |
                                |  (review & approve)  |
                                +----------+-----------+
                                           |
                                           v
+------------------+             +---------+----------+             +----------------------+
| Mailbox (IMAP)   +-----------> | Thread State Layer | <---------- | Context Ingestion     |
| read-only first  | evidence    | (thread lifecycle, |   facts     | (materials/habits)    |
+------------------+             | queue projection)  |             +----------+-----------+
                                 +---------+----------+                        |
                                           |                                   |
                                           v                                   |
                                 +---------+----------+                        |
                                 | Runtime Skeleton   |------------------------+
                                 | listener / action  |     typed context
                                 | template / audit   |
                                 +---------+----------+
                                           |
                                           v
                                 +---------+----------+
                                 | Automation Gates   |
                                 | read -> draft ->   |
                                 | controlled send    |
                                 +--------------------+
```

## Comparison: Anthropic `email-agent` Diagram

Anthropic project README architecture diagram:

![Anthropic Email Agent Architecture](docs/assets/anthropic-email-agent-architecture.png)

Main differences (this repo vs Anthropic demo):

- `Thread-first` vs `message/UI-event-first`: this repo models thread lifecycle and queue projection as core state.
- `Progressive automation` vs `direct demo flow`: this repo enforces `read-only -> draft -> controlled send`.
- `Context as structured plane` vs `ad-hoc session context`: user materials/habits are normalized for reuse.
- `Self-hostable runtime skeleton` vs `local demo app`: this repo emphasizes listener/action/template/audit evolution.

## Repository Map

```text
twinbox/
├── README.md
├── README.zh.md
├── SKILL.md
├── .beads/formulas/          # gastown formula definitions
│   ├── twinbox-phase{1-4}.formula.toml
│   └── twinbox-full-pipeline.formula.toml
├── agent/
│   ├── README.md
│   └── custom_scripts/
│       ├── types.ts
│       ├── listeners/
│       └── actions/
├── config/
│   ├── action-templates/
│   ├── context/
│   └── profiles/
├── docs/
│   ├── architecture.md
│   ├── guides/
│   │   └── gastown-operations.md   # gt operations guide
│   ├── plans/
│   │   ├── validation-framework.md
│   │   ├── gastown-integration.md
│   │   ├── oss-v1-plan.md
│   │   └── development-progress.md   # periodic dev snapshots
│   └── specs/thread-state-runtime.md
├── scripts/
│   ├── phase{1-4}_loading.sh       # deterministic I/O
│   ├── phase{1-4}_thinking.sh      # LLM inference
│   ├── phase4_gastown.sh           # unified Phase 4 gastown entrypoint
│   ├── register_canonical_root.sh  # register shared state root for worktrees
│   ├── twinbox_orchestrate.sh      # shared orchestration CLI
│   ├── run_pipeline.sh             # backward-compatible wrapper
│   └── twinbox_paths.sh            # shared code-root/state-root resolution
└── runtime/
```

## Quick Start 🚀

1. Read [architecture.md](docs/architecture.md).
2. Read [validation-framework.md](docs/plans/validation-framework.md).
3. Read [oss-v1-plan.md](docs/plans/oss-v1-plan.md).
4. If you want to validate mailbox access locally, run:
   - `bash scripts/check_env.sh`
   - `bash scripts/render_himalaya_config.sh`
   - `bash scripts/preflight_mailbox_smoke.sh --headless`
5. If you want to extend the runtime skeleton, start from:
   - [agent/README.md](agent/README.md)
   - [thread-state-runtime.md](docs/specs/thread-state-runtime.md)
   - [types.ts](agent/custom_scripts/types.ts)

## Runtime Direction Next

The next runtime layer will not clone Anthropic's `email-agent` directly.

It will keep this repository's strengths:

- progressive validation
- thread-centric workflow state
- human context plane
- controlled automation gates

And absorb the engineering pieces that matter:

- `listener` / `action` separation
- `template` / `instance` separation
- typed execution context
- execution audit trail
- enable/disable friendly extension surface

## Safety Boundaries

- Use app/client passwords only.
- Keep `.env` local and never commit it.
- Treat `runtime/` as local operational data.
- Do not auto-send until draft quality and approval flow are proven.
- Do not let user-supplied context silently overwrite mailbox facts.

## Publishing Note

This repository still contains locally generated validation materials under `docs/validation/` from a real mailbox study. Before a fully public release, you should review and sanitize any instance-specific files and history.

The open-source-facing architecture and template docs live outside `docs/validation/` and should remain the stable public surface.
