# Value-First Thread-Centric Email Copilot Architecture

## Goal

Build one stable email collaboration copilot core that can serve many companies, roles, and individuals without forking the implementation.

After early validation, the architecture goal is no longer "generic email automation first". It is:

- reduce missed high-priority follow-ups
- compress long threads into user-visible queues
- generate drafts only after read-only outputs prove useful
- keep sending behind explicit human approval

## Reality Check From Early Validation

Early validation often changes the architecture priority:

- some mailboxes are dominated by recurring workflow threads, not isolated messages
- the immediate user value is usually "what should I follow up today", not "can the bot send mail"
- thread state, evidence, and confidence often matter more than broad category coverage

Run-specific evidence should live in `docs/validation/` and `runtime/validation/`, not inside this architecture file.

## Design Principles

Hard things that should stay universal:

- mailbox connectivity
- message normalization
- thread reconstruction
- workflow state inference
- evidence linking
- idempotent sync
- logging, audit, and review workflow

Things that should stay customizable:

- internal domain map
- workflow dictionaries
- sender and team priority
- role-specific risk thresholds
- digest format
- draft style and tone
- escalation routing

## Value-First Rules

- Thread over message: decisions should be made on thread context, not single-message snapshots.
- Outputs before automation: the system must prove read-only value before drafting and sending.
- Evidence before confidence: every important conclusion should point to supporting messages or thread evidence.
- Dominant workflow before minority workflow: optimize what the mailbox mostly does first.
- Learn only from validated useful behavior: do not turn every edit into a rule.

## Seven-Layer Model

### 1. Transport Layer

Purpose:

- connect to IMAP/SMTP
- fetch folder, envelope, and message data
- save drafts or send mail only through controlled gates

Implementation:

- `himalaya` config rendered from `.env`
- no workflow or business logic here

### 2. Canonical Event and Thread Layer

Purpose:

- convert provider-specific mail data into one stable message and thread model

Canonical message fields:

- `message_id`
- `folder`
- `from`
- `to`
- `cc`
- `subject`
- `received_at`
- `body_text`
- `attachments`
- `flags`

Canonical thread fields:

- `thread_key`
- `participants`
- `last_activity_at`
- `message_count`
- `has_attachments`
- `internal_external`
- `workflow_type`
- `state`
- `state_confidence`
- `evidence_refs`

Why this matters:

- the rest of the pipeline should operate on stable thread facts, not provider quirks

### 3. Workflow State Layer

Purpose:

- infer what kind of workflow a thread belongs to
- infer which stage the thread is in now
- infer what the system is waiting on

Outputs:

- `workflow_type`
- `state`
- `owner_guess`
- `waiting_on`
- `due_hint`
- `risk_flags`
- `state_confidence`
- `evidence_refs`

This is often the real center of the system when recurring threads are process-shaped.

### 4. Value Surface Layer

Purpose:

- turn inferred thread state into user-visible outputs that save time immediately

Typical surfaces:

- `daily-urgent`
- `pending-replies`
- `blocked-threads`
- `weekly-brief`
- `project-watchlist`

Important rule:

- if this layer is not useful, the system should not move on to more aggressive automation

### 5. Policy and Profile Layer

Purpose:

- adapt the universal workflow engine to a role, team, or organization

Examples:

- internal domain allowlist
- workflow keyword dictionaries
- sender/team priority
- risk thresholds
- digest sections
- approval rules

Important rule:

- profile config may shape interpretation and presentation, but should not fork the core lifecycle engine

### 6. Draft and Action Layer

Purpose:

- produce structured assistant actions after value surfaces are stable

First-wave actions:

- `summarize`
- `classify`
- `remind`
- `draft_reply`

Later-stage actions:

- `send`
- `archive`
- `notify_external_system`

Important rule:

- sending should not be a first-class optimization target until read-only value is already proven

### 7. Review and Ops Layer

Purpose:

- keep the system safe, observable, and recoverable

Includes:

- approval gates
- audit log
- retry rules
- dead-letter handling
- evidence snapshots
- fallback model routing
- quality metrics for outputs and drafts

## Immediate Value Surfaces

The architecture should be judged by whether it can reliably produce:

- what I must follow up today
- what is waiting on me
- which important thread is blocked
- what changed this week without rereading the mailbox

These are easier for end users to perceive than abstract categories or generic automation claims.

## Recommended Repository Shape

```text
email-bot/
├── SKILL.md
├── .env
├── docs/
│   ├── architecture.md
│   └── validation/
│       └── instance-calibration-notes.md
├── scripts/
│   ├── check_env.sh
│   ├── render_himalaya_config.sh
│   ├── phase1_mailbox_census.sh
│   └── phase2_profile_inference.sh
├── config/
│   ├── policy.default.yaml
│   ├── profiles/
│   └── workflows/
└── runtime/
    ├── himalaya/
    ├── validation/
    ├── state/
    └── drafts/
```

## Decision Flow

```text
mail sync
-> normalize message event
-> reconstruct thread
-> infer workflow and state
-> attach evidence and confidence
-> generate user-visible queues
-> optionally build a draft plan
-> check review threshold
-> execute allowed action
-> log outcome and learn from validated edits
```

## Universal vs Customizable Split

Universal core:

- sync engine
- canonical message and thread schema
- thread reconstruction
- workflow inference engine
- evidence and confidence model
- value-surface generator
- draft runner
- audit and review gate

Customizable surface:

- internal domain map
- workflow dictionaries
- priority and SLA rules
- profile YAML
- prompt fragments
- digest templates
- escalation routing

## Success Metrics Users Can Feel

- fewer missed high-priority follow-ups
- faster morning triage
- clearer waiting-on-me list
- lower weekly summary effort
- lower draft edit burden

These matter more than the number of labels, actions, or profiles supported.

## What Not to Optimize Yet

- broad external auto-send
- CRM or ticket sync before value proof
- highly granular persona branching without workflow evidence
- one-off tenant hacks that bypass the thread model

## Practical Implementation Rule

If a requirement changes how one person sees outputs, put it in profile config.

If a requirement changes how one team names or prioritizes workflows, put it in workflow or policy config.

If a requirement improves thread reconstruction, state inference, evidence quality, or review safety for everyone, put it in the universal core.
