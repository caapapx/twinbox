<!--
Sync Impact Report
- Version: 1.1.1 → 1.2.0 (MINOR: Principle I layered read-default + policy-governed execution; semantic pack decoupling)
- Modified principles: I (read-only default + authorized side effects); Delivery Surface; Security Boundaries
- Added: references to ADR-001 / ADR-002; Planned contracts 003–006
- Removed: absolute ban wording that rejected all mailbox writes at design time without policy path
- Templates: still generic — ✅ no structural change required
- Follow-up: 006 must not ship until policy/audit/idempotency acceptance exists; 000 baseline is as-built fact
-->

# twinbox Constitution

## Core Principles

### I. Mailbox Mutation Boundary (NON-NEGOTIABLE)

- **Default**: IMAP access is read-only. Without an active Automation Policy match, forbidden mailbox operations remain send / move / delete / archive / flag.
- **Local-only mutation**: twinbox may mutate its own local queue (ack/snooze/done markers); that never writes back to the mail server.
- **Policy-governed side effects**: outbound or mailbox-mutating actions are allowed **only** when an explicit, versioned Automation Policy authorizes the process, target scope, and action type (see [ADR-002](../../docs/decisions/ADR-002-read-only-to-policy-governed-execution.md)). Unmatched proposals MUST refuse or hand off to a human; model confidence alone is not authorization.
- Every authorized side effect MUST be auditable, idempotent under a stable key, and must stop on failure with a recovery path. Implementation lives in Planned `specs/006-policy-governed-workflow-automation` until verified.

### II. Full Text Never Leaves twinbox (to platforms)

- Email full text (body, attachments) MUST NOT be persisted into Agent OS / platform-side storage.
- Platform-side consumers (Agent OS ingest and any future adapter) receive references only: stable message/thread IDs plus extracted attributes and bounded metadata (subject, sender, date, excerpt with bounded length).
- The local MCP session serving the mailbox owner MAY return decoded plain-text bodies and attachment metadata. That output is for the owner's agent, not a platform ingest envelope. Raw MIME, base64 payloads, and inline images MUST NOT be the default `body_text`.
- LLM prompts may carry body content transiently for extraction; extracted *platform* schemas contain no raw body fields.

### III. Classification Axes Stay in twinbox

- Mail classification axes and event types are defined and versioned inside twinbox (Semantic Packs and related tracked config). Example axes (person / thing / intent / urgency / sensitivity / thread) are illustrative, not a frozen platform enum.
- Axes MUST NOT be locked into Agent OS or any other downstream platform; twinbox may add, rename, or retire axes without a platform migration, as long as the output envelope shape is preserved (versioned opaque map/list).
- Downstream consumers treat axis values as opaque strings, never as enums compiled into their code.
- Domain rules (org trees, weekly roster rules, personal watch topics) live in declarative Semantic Packs, not in core engine entities ([ADR-001](../../docs/decisions/ADR-001-product-boundary-and-semantic-decoupling.md)).

### IV. Stable Tool Contract Surface

- The MCP tool entry points (`twinbox_*` in `mcp-server.mjs`) keep stable names and a stable request/response envelope shape (`ok` / `data` / `error` / `recovery_tool`).
- New capabilities are added as new tools or new fields inside `data`; existing fields are never removed or re-typed without a versioned deprecation path documented in the feature spec.
- Current implemented surface is the nine tools: `twinbox_sync`, `twinbox_latest_mail`, `twinbox_todo`, `twinbox_weekly`, `twinbox_thread_inspect`, `twinbox_queue_action`, `twinbox_extract`, `twinbox_status`, `twinbox_setup`.

### V. Credentials Never Leak

- Credentials (IMAP passwords, app passwords, tokens, encryption keys) MUST NOT appear in tool outputs, logs, specs/plans/tasks documents, or any git-tracked file.
- Tracked config files contain placeholders only; real values live in `~/.twinbox/` (git-ignored) or an encrypted local vault.
- Read APIs expose presence booleans (e.g. `password_set: true`), never values.
- Known as-built gap: local setup may still store plaintext passwords under `~/.twinbox/`; closing that gap is required work under Planned vault/`001`, not evidence that vault already exists ([000 baseline](../../specs/000-as-built-mcp-baseline/spec.md)).

## Delivery Surface

- **Implemented (as-built)**: local MCP stdio server + Python CLI on branch `master`; see [`specs/000-as-built-mcp-baseline`](../../specs/000-as-built-mcp-baseline/spec.md).
- **Active correctness contract**: [`specs/002-analysis-correctness`](../../specs/002-analysis-correctness/spec.md) (Draft until tasks converge).
- **Planned data plane**: [`specs/001-everything-mail-adapter`](../../specs/001-everything-mail-adapter/spec.md) (ingest / multi-account vault) — not current behavior.
- **Planned product contracts**: `003` semantic/event intelligence, `004` weekly report operations, `005` attention policy onboarding, `006` policy-governed automation — not current behavior.
- twinbox owns mail semantics and (when `006` ships) policy-gated execution; Agent OS owns aggregation. Neither side imports the other's internals.

## Technology Stack & Contracts

### Runtime

- Python core in `twinbox_core/` (CLI entry: `python3 -m twinbox_core.cli <cmd> --json`).
- MCP tool layer: `mcp-server.mjs` (Node, thin wrapper spawning the Python CLI).
- Config: `~/.twinbox/twinbox.json` (local, untracked) + tracked defaults under `config/`.

## Security Boundaries

- Do NOT perform mailbox mutation or outbound mail unless an Automation Policy explicitly authorizes it (Principle I).
- Do NOT log or return raw email bodies from *platform-facing* tool outputs.
- Do NOT write secrets into tracked files; mask secrets in all read APIs.
- Do NOT let downstream platforms dictate twinbox's classification taxonomy.
- Do NOT treat Semantic Packs as executable code bundles.

## Trunk

- **`master`** is the default trunk (MCP Skill / CLI). Do not keep a long-lived `feat/*` trunk.
- **`archive/openclaw-monolith`** is the frozen pre-MCP monolith. It is not the default branch.
- Do not call the trunk `openclaw-skill`, `feat/mcp-server`, or `main`.

## Development Workflow

- Commit message format: `type: short description`.
- No automatic commit / push.
- Debug: after editing `twinbox_core`, run `python3 -m twinbox_core.cli <cmd> --json` directly; no daemon restart needed.
- SpecKit: constitution → specify → plan → tasks → analyze → implement → converge. Change classification in `docs/governance/change-classification.md`.
- Long-lived decisions: `docs/decisions/` ADRs.

## Governance

This constitution supersedes all other practices for this repository. Amendments require documentation, approval, and a migration plan. All PRs/reviews must verify compliance with the principles above; complexity must be justified.

**Version**: 1.2.0 | **Ratified**: 2026-08-26 | **Last Amended**: 2026-09-04
