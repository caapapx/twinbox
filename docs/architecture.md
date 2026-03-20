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
- recurring task habits
- user-confirmed ownership and glossary facts

## Value-First Rules

- Thread over message: decisions should be made on thread context, not single-message snapshots.
- Outputs before automation: the system must prove read-only value before drafting and sending.
- Evidence before confidence: every important conclusion should point to supporting messages or thread evidence.
- Dominant workflow before minority workflow: optimize what the mailbox mostly does first.
- Learn only from validated useful behavior: do not turn every edit into a rule.
- Human-supplied context is first-class input, but it must be typed, source-labeled, and time-bounded.

## Supported Initialization Modes

The architecture should support three equivalent entry modes:

- agent-only initialization
- guided chat or manual paste initialization
- hybrid initialization with mailbox sync plus user-supplied materials

All three should converge into the same normalized context artifacts and the same downstream inference pipeline.

## Shared State Root for Multi-Worktree Execution

When Gastown runs work in linked worktrees, the system must separate executable code from instance-local state.

Definitions:

- `code root`: the current checkout that provides tracked scripts, formula files, and implementation logic
- `state root`: the canonical checkout that provides `.env`, `runtime/context/`, `runtime/validation/`, and `docs/validation/`

Resolution order:

- `TWINBOX_CANONICAL_ROOT`
- `~/.config/twinbox/canonical-root`
- current checkout, but only for a normal repository checkout

Operational rules:

- linked worktrees must fail fast if no canonical root is configured
- parallel workers may execute from different `code root` paths, but they must read and write the same `state root`
- instance-local artifacts stay in the state root; they are not copied into each worker checkout
- this pattern applies to Phase 1-4; it is especially visible in Phase 4, where `loading`, `urgent/pending`, `sla-risks`, `weekly-brief`, and `merge` need to share the same context pack and raw outputs

## Human Context Plane

This is a cross-cutting input plane, not a tenant-specific hack.

Purpose:

- ingest work materials such as spreadsheets, documents, PDFs, screenshots, and notes
- ingest user-declared recurring habits and calendar-like obligations
- ingest user-confirmed facts that correct low-confidence inference
- keep provenance so the system can explain whether something came from mail, material, or user declaration

Typical inputs:

- project ledgers and execution trackers
- weekly or monthly reporting obligations
- org-role descriptions and glossary mappings
- corrections such as "this thread is usually CC-only" or "this sender is a system bot"

Reader strategy:

- prefer pluggable document readers such as spreadsheet parsers, OCR pipelines, or MCP-backed office document services
- if a material cannot be parsed reliably, store the file manifest plus a user-provided summary instead of dropping it

Normalized context fact fields:

- `context_id`
- `source_type`
- `source_ref`
- `fact_type`
- `scope`
- `applies_to`
- `value`
- `valid_from`
- `valid_to`
- `freshness`
- `confidence`
- `confirmed_by_user`
- `merge_policy`
- `evidence_refs`

Merge rules:

- raw mailbox facts should never be overwritten silently
- user-confirmed facts may override low-confidence inference, but the override must stay visible
- recurring habits and external materials may add due windows, owner hints, glossary mappings, and reporting obligations even when mail alone cannot
- expired or stale context should reduce confidence automatically

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
- human context should enrich this layer through references, not by bypassing the canonical model

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
- `context_refs`

This is often the real center of the system when recurring threads are process-shaped.

### 3.5. Attention Gate

Purpose:

- progressively filter threads between phases so downstream layers only spend tokens on threads that matter
- each phase narrows the attention window: full envelope set → intent-filtered → profile-filtered → lifecycle-modeled → actionable

How it works:

- each validation phase outputs an `attention-budget.yaml` with three thread sets: `focus`, `deprioritize`, `skip`
- the next phase reads the previous budget and only does deep work (body sampling, draft generation) on the `focus` set
- `skip` threads are not deleted — they stay in raw data for audit and recall
- user corrections via `user_confirmed_fact` can promote a thread from `skip` back to `focus` at any time

Attention narrowing by phase:

| Phase | Gate action | Typical reduction |
|---|---|---|
| Phase 1 | mark noise candidates (bot notifications, empty threads, duplicate subscriptions) | ~15-25% of envelopes marked skip |
| Phase 2 | add exclusion rules based on persona (irrelevant domains, unrelated intent types) | ~10-15% additional deprioritize |
| Phase 3 | mark unmodeled threads (cannot fit any lifecycle flow) | ~20-30% deprioritized |
| Phase 4 | mark low-signal threads (modeled but no actionable signal in body) | focus narrows to ~30-40% of original |
| Phase 5 | mark draft-excluded threads (too risky, insufficient context) | draft candidates typically <10% of original |

Why this matters:

- without an attention gate, Phase 4 body sampling would consume tokens on the full envelope set
- with the gate, Phase 4 only samples a smaller focus set, cutting token cost materially while improving review quality
- the gate also improves precision: fewer noise threads means fewer false positives in urgent/pending queues

Important rules:

- the gate is advisory, not destructive — raw data is never modified
- every skip decision must have a recorded reason
- attention budgets are cumulative: each phase inherits and refines the previous budget

### 4. Value Surface Layer

Purpose:

- turn inferred thread state into user-visible outputs that save time immediately

Typical surfaces:

- `daily-urgent`
- `pending-replies`
- `blocked-threads`
- `weekly-brief`
- `project-watchlist`

These surfaces may contain two kinds of urgency:

- live thread urgency inferred from mail activity
- scheduled obligation urgency inferred from normalized user context

The source of urgency must remain explicit.

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
- recurring cadence rules
- glossary and alias maps

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

## Runtime Extension Surface

The first public runtime should expose a small but explicit extension model instead of hiding behavior in prompts.

### Listener Layer

Purpose:

- react to normalized thread-state events
- refresh value surfaces and low-risk reminders
- stay read-oriented through early phases

Preferred event types:

- `thread_entered_state`
- `thread_sla_risk`
- `daily_digest_time`
- `context_updated`
- `confidence_below_threshold`

### Action Template Layer

Purpose:

- define reusable capabilities without binding them to one thread
- keep high-risk behavior reviewable and phase-gated

Examples:

- `summarize_thread`
- `build_daily_digest`
- `remind_owner`
- `draft_reply`

### Action Instance Layer

Purpose:

- materialize one concrete action proposal from a template plus thread/context state
- provide review-ready payloads with evidence, confidence, and due hints

Important rule:

- instances belong to runtime data and review flows, not static config files

### Execution Audit Layer

Purpose:

- record every listener emission, draft proposal, approval, rejection, and send attempt
- make automation reviewable before it becomes trusted

Important rule:

- every meaningful action must leave a machine-readable audit trail

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
├── agent/
│   ├── README.md
│   └── custom_scripts/
│       ├── actions/
│       ├── listeners/
│       └── types.ts
├── SKILL.md
├── .env
├── docs/
│   ├── architecture.md
│   ├── release/
│   ├── specs/
│   └── validation/
│       └── README.md
├── scripts/
│   ├── check_env.sh
│   ├── render_himalaya_config.sh
│   ├── phase1_mailbox_census.sh
│   └── phase2_profile_inference.sh
├── config/
│   ├── action-templates/
│   ├── policy.default.yaml
│   ├── context/
│   ├── profiles/
│   └── workflows/
└── runtime/
    ├── context/
    │   ├── material-manifest.json
    │   ├── material-extracts/
    │   ├── manual-habits.yaml
    │   ├── manual-facts.yaml
    │   └── context-pack.json
    ├── himalaya/
    ├── validation/
    ├── state/
    └── drafts/
```

## Decision Flow

```text
mail sync
-> normalize message event
-> ingest human and material context
-> normalize context facts with provenance
-> reconstruct thread
-> infer workflow and state
-> apply attention gate (read previous budget, classify focus/deprioritize/skip)
-> attach evidence and confidence (focus set only for deep analysis)
-> generate user-visible queues
-> output updated attention-budget.yaml
-> optionally build a draft plan (focus set only)
-> check review threshold
-> execute allowed action
-> log outcome and learn from validated edits
```

## Universal vs Customizable Split

Universal core:

- sync engine
- canonical message and thread schema
- canonical context fact schema
- thread reconstruction
- workflow inference engine
- attention gate and progressive budget
- context merge and provenance model
- evidence and confidence model
- value-surface generator
- draft runner
- audit and review gate

Customizable surface:

- internal domain map
- workflow dictionaries
- priority and SLA rules
- profile YAML
- manual habits and confirmed facts
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

If a requirement is a user-supplied recurring task, uploaded work material, or explicit factual correction, put it in normalized context artifacts with provenance and validity metadata.

If a requirement improves thread reconstruction, state inference, evidence quality, or review safety for everyone, put it in the universal core.
