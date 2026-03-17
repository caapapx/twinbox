# Thread-State Listeners

Place future listener implementations here.

Listeners in this project are not raw mailbox event hooks. They should react to normalized thread-state events such as:

- `thread_entered_state`
- `thread_sla_risk`
- `daily_digest_time`
- `context_updated`
- `confidence_below_threshold`

## Rules

1. Prefer read-only outputs and reminder proposals.
2. Do not send mail directly from a listener.
3. Emit evidence-backed suggestions only.
4. Respect phase gates from the validation plan.
5. Write audit records for every emitted recommendation.
