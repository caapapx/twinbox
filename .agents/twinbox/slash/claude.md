# Twinbox Skill for Claude Code

## Session and Verification
Follow the same patterns as documented in SKILL.md and SKILL-EN.md:
- Always call matching plugin tool FIRST, then write text summary
- Never narrate "let me run" or "need to sync first" without tool call in same turn
- For latest mail / inbox: call twinbox_latest_mail immediately
- At push_subscription: twinbox_push_confirm_onboarding (no session param)
- At routing_rules: twinbox_onboarding_finish_routing_rules
- At profile_setup: twinbox_onboarding_advance with profile_notes + calibration_notes in same turn

## Slash Command Usage
When using Claude Code slash commands:
- `/twinbox latest-mail` → Execute `twinbox task latest-mail --json` then summarize
- `/twinbox todo` → Execute `twinbox task todo --json` then summarize
- `/twinbox weekly` → Execute `twinbox task weekly --json` then summarize
- `/twinbox thread-progress <thread-id>` → Execute `twinbox task progress <thread-id> --json` then summarize
- `/twinbox mailbox-status` → Execute `twinbox task mailbox-status --json` then summarize
- `/twinbox schedule list` → Execute `twinbox schedule list --json` then summarize
- `/twinbox schedule enable <job>` → Execute `twinbox schedule enable <job> --json` then summarize
- `/twinbox schedule disable <job>` → Execute `twinbox schedule disable <job> --json` then summarize
- `/twinbox queue dismiss <thread-id> --reason "..."` → Execute with --json then summarize
- `/twinbox queue complete <thread-id> --action-taken "..."` → Execute with --json then summarize
- `/twinbox context import-material <file> --intent <intent>` → Execute with --json then summarize

## Tool Chain Integrity
Never end a turn with only tool calls and no text response. Always follow tool execution with a visible summary.

See SKILL.md and SKILL-EN.md for complete session handling guidelines.