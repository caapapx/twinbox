# Agent Runtime Skeleton

This directory is the committed skeleton for the future `email-bot` runtime extension surface.

It is intentionally `spec-first`.

That means:

- the interfaces are committed before the runtime is fully implemented
- contributors can extend against stable contracts
- the repository can be published without pretending the listener/action runtime already exists

## Layout

- `custom_scripts/types.ts`: shared type contracts for listeners, actions, context refs, and audit records
- `custom_scripts/listeners/`: committed location for thread-state listener implementations
- `custom_scripts/actions/`: committed location for action handlers and execution adapters

## Design Constraints

1. Use thread-state events, not raw provider events, as the main trigger surface.
2. Do not encode tenant-specific workflow assumptions in code.
3. Read from normalized mailbox and context artifacts instead of direct ad hoc prompts.
4. Keep send-capable actions phase-gated and review-gated.
5. Emit audit records for every meaningful action or recommendation.

## Intended Evolution

Near-term:

- add listener registration and dry-run execution
- add action-template loading from `config/action-templates/`
- add JSONL audit output under `runtime/audit/`

Later:

- enable/disable lifecycle
- scheduled execution
- OpenClaw review surfaces
- controlled send pipeline
