# twinbox 📮

[English](./README.md) | [中文](./README.zh.md)

An OpenClaw-native, thread-centric email copilot: understand thread state first, then unlock automation step by step.

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
- a stable progressive validation template for OpenClaw or manual initialization
- a context-ingestion model for user-provided materials and habits
- a new spec-first runtime skeleton for listeners, actions, templates, and audit logging

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

### LLM Pipeline (Loading → Thinking)

Each Phase is split into deterministic I/O (loading) and LLM inference (thinking):

| Phase | Loading | Thinking |
|-------|---------|----------|
| 1 | envelope + body sampling | Intent classification |
| 2 | Phase 1 output + enriched context | Persona + business hypotheses |
| 3 | thread grouping + upstream aggregation | Lifecycle flow + stage classification |
| 4 | recent bodies + lifecycle context | daily-urgent / pending-replies / sla-risks |

```bash
# Single phase
bash scripts/phase1_loading.sh && bash scripts/phase1_thinking.sh

# Full pipeline
bash scripts/run_pipeline.sh

# Single phase via pipeline
bash scripts/run_pipeline.sh --phase 2
```

### Gastown Multi-Agent Orchestration

twinbox integrates with [gastown](https://github.com/steveyegge/gastown) for multi-agent orchestration:

```bash
# Sling a Phase 1 formula to a polecat worker
gt sling twinbox-phase1 twinbox --create
```

Execution chain: `gt sling` → spawn polecat → cook formula → execute loading/thinking → submit MR → refinery merge → witness monitoring

See [Gastown Operations Guide](docs/guides/gastown-operations.md).

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
│   │   └── gastown-multi-agent-integration.md
│   ├── openclaw-progressive-validation-plan.md
│   ├── release/open-source-v1-plan.md
│   └── specs/thread-state-runtime.md
├── scripts/
│   ├── phase{1-4}_loading.sh       # deterministic I/O
│   ├── phase{1-4}_thinking.sh      # LLM inference
│   └── run_pipeline.sh             # fallback serial orchestration
└── runtime/
```

## Quick Start 🚀

1. Read [architecture.md](docs/architecture.md).
2. Read [openclaw-progressive-validation-plan.md](docs/openclaw-progressive-validation-plan.md).
3. Read [open-source-v1-plan.md](docs/release/open-source-v1-plan.md).
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
