# Twinbox Command Usage for Claude Code

When NOT using slash commands, use explicit natural language prompts:

## Recommended Patterns
- "请先实际执行 `twinbox task latest-mail --json`，然后基于真实命令输出返回：generated_at、summary、urgent_top_k 的 thread_key、pending_count。"
- "请运行 twinbox task todo --json 并返回 pending_count 和前 3 个需要处理的 thread_key。"
- "请运行 twinbox task weekly --json 并基于结果告诉我最近一周的重要线程和行动建议。"
- "请执行 twinbox task mailbox-status --json 并把原始 JSON 结果原样贴出来，再用一句话总结当前状态。"

## Critical Rules
1. **Always execute the matching tool FIRST** - never just read SKILL.md and narrate
2. **Never end a turn with only text when user asked for mail/todo/digest/onboarding action**
3. **Never duplicate the same sentence or near-duplicate paragraphs in one assistant message**
4. **If no twinbox_* tools are available in this session, output one line saying the plugin or twinbox agent is required**
5. **Bootstrap new sessions** by having the agent first read SKILL.md, then immediately execute a twinbox command in the SAME turn

## Session Handling
- Fresh sessions reduce tool-chain dropout
- After skill/env changes, use a new session
- When UI shows empty bubble after tool call, it's usually a model/tool-turn limitation - run the command in host shell and paste output

See SKILL.md and SKILL-EN.md for complete details.