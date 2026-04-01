# Twinbox Command Mode (platform-agnostic)

For platform-specific skills, see:
- Claude Code: `.claude/skills/twinbox/SKILL.md`
- Cursor: `.cursor/skills/twinbox/SKILL.md`
- Codex: `.codex/skills/twinbox/AGENTS.md`
- OpenClaw: root `SKILL.md` / `SKILL-EN.md`

## Generic Usage

When using any CLI/agent that supports shell commands:

```bash
# Latest mail
twinbox task latest-mail --json

# Todo
twinbox task todo --json

# Weekly
twinbox task weekly --json

# Thread progress
twinbox task progress "query" --json

# Queue management
twinbox queue dismiss THREAD_ID --reason "..." --json
twinbox queue complete THREAD_ID --action-taken "..." --json
twinbox queue restore THREAD_ID --json

# Schedule
twinbox schedule list --json
twinbox schedule enable JOB_NAME --json
twinbox schedule disable JOB_NAME --json

# Onboarding
twinbox onboarding start --json
twinbox onboarding status --json
twinbox onboarding next --json

# Preflight & config
twinbox mailbox preflight --json
twinbox config show --json
twinbox daemon status --json
```

## Rule

Always append `--json` to get machine-readable output. Summarize the output in text after execution.
