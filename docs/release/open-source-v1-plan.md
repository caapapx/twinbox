# Open Source V1 Refactor Plan

## Goal

Turn `email-bot` from a validation workspace plus shell scripts into a publishable product skeleton.

The target for the first open-source release is not a complete email agent runtime. The target is:

- a clear product position
- a stable architecture story
- a reusable initialization and validation framework
- a minimal runtime extension skeleton that future contributors can implement against

## Baseline Decision

Use this comparison baseline:

- keep the strengths of this repository: `progressive validation`, `thread-centric workflow modeling`, `human context plane`, `OpenClaw-native self-hosted fit`
- absorb the strongest engineering ideas from Anthropic's `email-agent`: `listener/action split`, `template/instance split`, `typed context`, `execution audit`, `operable extension surface`
- do not copy `message-first`, `Gmail-centric`, or `early auto-send` assumptions

## What Stays

These remain core to the project and should not be regressed during refactor:

- read-only value before automation
- thread state as the main inference unit
- context normalization for user materials, habits, and confirmed facts
- explicit provenance for every important conclusion
- gradual promotion path: `read-only -> draft -> controlled send`

## What Must Be Added

### 1. Listener Layer

Purpose:

- handle low-risk, read-oriented triggers
- respond to thread-state changes instead of only raw message events

Target events:

- `thread_entered_state`
- `thread_sla_risk`
- `daily_digest_time`
- `context_updated`
- `confidence_below_threshold`

### 2. Action Template Layer

Purpose:

- define reusable, reviewable action capabilities without binding them to a single thread instance

Examples:

- `build_daily_digest`
- `remind_owner`
- `draft_reply`
- `summarize_thread`

### 3. Action Instance Layer

Purpose:

- turn a template into a concrete action card for one thread, one queue, or one review surface

Requirements:

- evidence refs
- confidence
- phase gate
- risk level
- review requirement
- context refs

### 4. Execution Audit Layer

Purpose:

- log every draft, reminder, approval, rejection, and send attempt
- make every action replayable and reviewable

Minimum output:

- JSONL records under `runtime/audit/`
- stable record schema
- actor, phase, template, instance, result, evidence, and timestamps

## V1 Deliverables

The first public release should contain at least:

- rewritten `README.md`
- stable `docs/architecture.md`
- stable `docs/openclaw-progressive-validation-plan.md`
- `docs/release/open-source-v1-plan.md`
- `docs/specs/thread-state-runtime.md`
- `agent/custom_scripts/types.ts`
- committed folders for `agent/custom_scripts/listeners/`, `agent/custom_scripts/actions/`, `config/action-templates/`

## Explicit Non-Goals For V1

Do not try to ship these in the first open-source release:

- a full frontend
- multi-provider mailbox abstraction beyond current `himalaya` path
- broad auto-send
- hardcoded company workflows
- implicit learning from all user edits

## Suggested Repository Shape

```text
email-bot/
├── agent/
│   ├── README.md
│   └── custom_scripts/
│       ├── actions/
│       ├── listeners/
│       └── types.ts
├── config/
│   ├── action-templates/
│   ├── context/
│   ├── profiles/
│   └── policy.default.yaml
├── docs/
│   ├── architecture.md
│   ├── openclaw-progressive-validation-plan.md
│   ├── release/
│   └── specs/
├── scripts/
└── runtime/
```

## Near-Term Milestones

### Milestone A: publishable skeleton

Ship now:

- product positioning
- runtime skeleton directories
- typed contracts
- runtime spec docs

### Milestone B: thread-state listeners manager

Add:

- listener registration
- enable/disable flags
- scheduled trigger support
- dry-run mode

### Milestone C: action templates and instances

Add:

- template loader
- instance materializer
- review surface payloads
- phase gates

### Milestone D: audit and review loop

Add:

- JSONL audit trail
- approval/rejection state transitions
- diff between proposed and approved drafts

## Public Release Checklist

Before making the repository public, verify:

1. no mailbox credentials are tracked
2. no instance-specific email addresses, domains, project names, or subjects remain in public-facing docs
3. validation examples are redacted or moved out of public history
4. `.env` remains local-only
5. a license file is chosen and added
6. the README does not claim runtime features that do not exist yet
7. contributors can understand where to extend the system without reading private validation artifacts

## Release Principle

This repository should be publishable because the public surface is:

- generic
- reusable
- honest about current completeness
- structured for contributors

It should not depend on one mailbox instance remaining in the repository forever.
