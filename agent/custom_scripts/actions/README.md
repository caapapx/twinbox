# Actions

Place future action handlers here.

An action is a reviewable, concrete operation derived from a template and an execution context.

Examples:

- `summarize_thread`
- `build_daily_digest`
- `remind_owner`
- `draft_reply`
- `send_reply`

## Rules

1. Every action must originate from a declared template.
2. Every action instance must carry `why`, `confidence`, `evidence_refs`, and `phase_gate`.
3. `draft_reply` may appear before `send_reply`.
4. `send_reply` must remain review-gated and policy-gated.
5. Every execution must produce an audit record.
