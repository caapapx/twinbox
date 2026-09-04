<!--
Sync Impact Report
- Version: 1.1.0 → 1.1.1 (PATCH: default trunk renamed main → master)
- Modified principles: II Full Text Never Leaves twinbox (clarified local MCP vs platform)
- Added sections: Delivery Surface; Trunk
- Removed sections: none
- Templates: plan/spec/tasks Constitution Check still generic — ✅ no structural change required
- Follow-up: specs/001 marked Planned; 002 is the active analysis-correctness contract
-->

# twinbox Constitution

## Core Principles

### I. Read-Only Mailbox (NON-NEGOTIABLE)

- IMAP access is strictly read-only: forbidden operations are send / move / delete / archive / flag.
- The only permitted state mutation is twinbox's own local queue (ack/snooze/done markers), which never writes back to the mail server.
- Any new tool, module, or integration that needs a write-capable mailbox operation is rejected at design time, not at review time.

### II. Full Text Never Leaves twinbox (to platforms)

- Email full text (body, attachments) MUST NOT be persisted into Agent OS / platform-side storage.
- Platform-side consumers (Agent OS ingest and any future adapter) receive references only: stable message/thread IDs plus extracted attributes and bounded metadata (subject, sender, date, excerpt with bounded length).
- The local MCP session serving the mailbox owner MAY return decoded plain-text bodies and attachment metadata. That output is for the owner's agent, not a platform ingest envelope. Raw MIME, base64 payloads, and inline images MUST NOT be the default `body_text`.
- LLM prompts may carry body content transiently for extraction; extracted *platform* schemas contain no raw body fields.

### III. Classification Axes Stay in twinbox

- Mail classification axes (person / thing / intent / urgency / sensitivity / thread, and any future axis) are defined and versioned inside twinbox (e.g. `config/extract-profiles.yaml`).
- Axes MUST NOT be locked into Agent OS or any other downstream platform; twinbox may add, rename, or retire axes without a platform migration, as long as the output envelope shape is preserved.
- Downstream consumers treat axis values as opaque strings, never as enums compiled into their code.

### IV. Stable Tool Contract Surface

- The MCP tool entry points (`twinbox_*` in `mcp-server.mjs`) keep stable names and a stable request/response envelope shape (`ok` / `data` / `error` / `recovery_tool`).
- New capabilities are added as new tools or new fields inside `data`; existing fields are never removed or re-typed without a versioned deprecation path documented in the feature spec.
- Current implemented surface is the nine tools: `twinbox_sync`, `twinbox_latest_mail`, `twinbox_todo`, `twinbox_weekly`, `twinbox_thread_inspect`, `twinbox_queue_action`, `twinbox_extract`, `twinbox_status`, `twinbox_setup`.

### V. Credentials Never Leak

- Credentials (IMAP passwords, app passwords, tokens, encryption keys) MUST NOT appear in tool outputs, logs, specs/plans/tasks documents, or any git-tracked file.
- Tracked config files contain placeholders only; real values live in `~/.twinbox/` (git-ignored) or an encrypted local vault.
- Read APIs expose presence booleans (e.g. `password_set: true`), never values.

## Delivery Surface

- **Implemented**: local MCP stdio server + Python CLI on branch `master`.
- **Planned**: Agent OS Everything ingest / multi-account vault (`specs/001-everything-mail-adapter`). That contract is not implemented; do not describe it as current behavior.
- twinbox owns mail semantics; Agent OS owns aggregation. Neither side imports the other's internals.

## Technology Stack & Contracts

### Runtime

- Python core in `twinbox_core/` (CLI entry: `python3 -m twinbox_core.cli <cmd> --json`).
- MCP tool layer: `mcp-server.mjs` (Node, thin wrapper spawning the Python CLI).
- Config: `~/.twinbox/twinbox.json` (local, untracked) + tracked defaults under `config/`.

## Security Boundaries

- Do NOT add any server-side mailbox mutation.
- Do NOT log or return raw email bodies from *platform-facing* tool outputs.
- Do NOT write secrets into tracked files; mask secrets in all read APIs.
- Do NOT let downstream platforms dictate twinbox's classification taxonomy.

## Trunk

- **`master`** is the default trunk (MCP Skill / CLI). Do not keep a long-lived `feat/*` trunk.
- **`archive/openclaw-monolith`** is the frozen pre-MCP monolith. It is not the default branch.
- Do not call the trunk `openclaw-skill`, `feat/mcp-server`, or `main`.

## Development Workflow

- Commit message format: `type: short description`.
- No automatic commit / push.
- Debug: after editing `twinbox_core`, run `python3 -m twinbox_core.cli <cmd> --json` directly; no daemon restart needed.
- SpecKit: constitution → specify → plan → tasks → analyze → implement → converge. Change classification in `docs/governance/change-classification.md`.

## Governance

This constitution supersedes all other practices for this repository. Amendments require documentation, approval, and a migration plan. All PRs/reviews must verify compliance with the principles above; complexity must be justified.

**Version**: 1.1.1 | **Ratified**: 2026-08-26 | **Last Amended**: 2026-09-04
