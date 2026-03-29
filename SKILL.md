---
name: twinbox
description: >-
  Twinbox mailbox skill. REQUIRED behavior: after running any twinbox CLI
  command, always produce a text summary for the user — never stop with tool
  calls alone; a turn with no text reply is a failure. If a command fails
  (e.g. missing activity-pulse.json), explain why and suggest the fix (run
  twinbox-orchestrate schedule --job daytime-sync). Use for: email preflight,
  latest-mail, queue triage, onboarding (start/status/next), weekly digest,
  thread progress, schedule management, and OpenClaw deploy diagnostics via
  `twinbox` / `twinbox-orchestrate`.
metadata: {"openclaw":{"requires":{"env":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"]},"primaryEnv":"IMAP_LOGIN","login":{"mode":"password-env","runtimeRequiredEnv":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"],"optionalDefaults":{"MAIL_ACCOUNT_NAME":"myTwinbox","MAIL_DISPLAY_NAME":"{MAIL_ACCOUNT_NAME}","IMAP_ENCRYPTION":"tls","SMTP_ENCRYPTION":"tls"},"stages":["unconfigured","validated","mailbox-connected"],"preflightCommand":"twinbox mailbox preflight --json"}}}
---

# twinbox

Use this skill for Twinbox mailbox onboarding, read-only preflight checks, latest-mail summaries, queue triage, thread progress lookup, weekly digest lookup, queue refresh, and deployment debugging in OpenClaw-managed environments.

## Session and verification (mechanism, not IDE-specific)

Twinbox mail state is produced by **`twinbox` / `twinbox-orchestrate` on the OpenClaw host** and consumed inside a **`twinbox` agent session** (tool policy + session history + Gateway). Regressions such as empty assistant payloads, “read SKILL only”, or silent turns are addressed by **session design and test procedure** (fresh session when needed, bootstrap turn, split long suites, optional **`plugin-twinbox-task`** tools), documented in `openclaw-skill/prompt-test.md` and `scripts/run_openclaw_prompt_tests.py` — not by relabeling the client app.

Known OpenClaw limitation (confirmed 2026-03-27 on `xfyun-mass` / `astron-code-latest`): OpenClaw injects this skill's **`description`** into the system prompt, but the rest of `~/.openclaw/skills/twinbox/SKILL.md` is visible only if the agent explicitly reads the file. On this model, turns that call generic `exec` can stop immediately after the tool call and return `payloads=[]`, `assistant.content=[]`, or a short stub such as `让我执行命令：`. This is most visible in onboarding because there is currently no native `twinbox_onboarding_*` tool; `twinbox onboarding start|status|next --json` goes through generic `exec`.

Recommended hosted workaround: start a **fresh `twinbox` session**, send one **bootstrap** turn that tells the agent to read `~/.openclaw/skills/twinbox/SKILL.md` first and then run the exact `twinbox ... --json` command in the same turn, and treat host-shell `twinbox ... --json` output as the source of truth for machine-readable verification if the session still returns empty payloads. Prefer native plugin tools where they exist; use the bootstrap path mainly for onboarding and other `exec`-only flows.

## Turn contract

For **all** twinbox command executions (mail, queue, digest, onboarding, deploy, schedule, rule, etc.): run the matching `twinbox` command with `--json`, then reply with a text summary. Never end with only tool calls and no text response. A turn with `payloads=[]` or `assistant.content=[]` is always a failure.

### Onboarding: advancing after the user replies (critical)

Stages such as `profile_setup`, `material_import`, `routing_rules`, and `push_subscription` are **dialogue-first**: collect the user's answer in chat, but **the persisted stage only advances when** you run `twinbox onboarding next --json` on the Twinbox host. For **profile_setup**, add **`--profile-notes "…"`** for role/habits/preferences, **`--calibration-notes "…"`** for “this week’s focus / what to ignore / top priorities”, and when relevant **`--cc-downweight on|off`** to persist whether CC/group threads should be structurally downweighted. These are stored in `runtime/context/human-context.yaml` (`profile_notes` / `calibration`) plus `twinbox.json.preferences.cc_downweight.enabled`. Phase 2/3 **and Phase 4** **`context-pack.json`** pick up the human-context fields as `human_context.onboarding_profile_notes` / `human_context.calibration_notes`; Phase 4 score post-processing reads the CC downweight preference from `twinbox.json`. Legacy `manual-facts.yaml` / `manual-habits.yaml` / `instance-calibration-notes.md` / onboarding `profile_data.*` inputs are auto-migrated on first read; afterward the unified file is authoritative. For other stages there is not yet an equivalent flag—use `twinbox context upsert-fact` / `profile-set` if you need durable prose. For **material_import**, first show the default weekly template at `config/weekly-template.md`; if the user wants different section titles/order/wording, turn that natural-language request into a Markdown template and import it with `twinbox context import-material FILE --intent template_hint`, then rerun Phase 4 or wait for the next weekly refresh.

On stacks where generic `exec` often drops payloads (`xfyun-mass` / `astron-code-latest`, etc.), use this pattern: **in the same assistant turn** as (or immediately after) acknowledging the user's reply, run `twinbox onboarding next --json`, then print a **visible** summary of `completed_stage`, `current_stage`, and the next `prompt`. Do not end the turn with only a tool call.

**Recovery if the UI went idle** after the user sent their profile (TUI shows `connected | idle`, no assistant text): send a short follow-up that forces CLI + prose, e.g. run `twinbox onboarding status --json` and `twinbox onboarding next --json`, then summarize both. If payloads stay empty, run the same commands in a **host shell** and continue from printed JSON.

**Session:** prefer a **dedicated `twinbox` agent** for onboarding handoff — not `main` — so skill injection, tools, and `openclaw-skill/DEPLOY.md` match.

## Use For

- Mailbox env collection and login preflight via `twinbox mailbox preflight --json`
- Summarizing "latest mail situation", "today's updates", or "what happened today"
- Listing urgent items, pending replies, and SLA-ish risks from current artifacts
- Dismissing, completing, or restoring queue-visible threads through `twinbox queue ...`
- Listing, overriding, or resetting runtime schedule config through `twinbox schedule ...`
- Looking up the latest progress of one thread, subject, project, or business keyword
- Showing daily / pulse / weekly digests from current Twinbox artifacts
- Suggesting actions or review items from current queue state
- Checking whether Twinbox runtime is mounted and runnable in the current OpenClaw host
- Refreshing pipeline artifacts with `twinbox-orchestrate schedule --job ...` or `run --phase <n>`
- Explaining urgent / pending / SLA / weekly outputs under `runtime/validation/phase-4/`
- Diagnosing why a deployed Twinbox/OpenClaw skill is still missing, blocked, stale, or not refreshing
- One-shot **host wiring** for OpenClaw: roots init, `openclaw.json` merge, `SKILL.md` sync, gateway restart (`twinbox deploy openclaw`); narrow undo via `twinbox deploy openclaw --rollback` (does not remove `~/.twinbox`)

## Task Entrypoints

**REQUIRED STEPS for any task request:**

1. Match the user's request to a command in the list below.
2. Execute that command now.
3. Write a text answer summarizing the real output.

Reading this file is step 0 only. The turn is **not complete** until you have executed a command (step 2) and written a text answer (step 3). If you have only read files or memory so far, proceed to step 2 immediately — do not end the turn.

| User intent | Command |
|-------------|---------|
| Latest mail / today summary / "最新邮件情况" / 帮我查看下最新的邮件情况 | `twinbox task latest-mail --json` (use `--unread-only` if user asks for unread) |
| "我有哪些待办 / 待回复 / 最值得关注的线程" | `twinbox task todo --json` |
| 暂时忽略某个线程 / 标记已处理但先别再提醒 | `twinbox queue dismiss THREAD_ID --reason "..." --json`；OpenClaw 插件：`twinbox_queue_dismiss`（`thread_id`，可选 `reason`） |
| 标记某个线程已完成（须落库，聊天里打 ✅ 不算） | `twinbox queue complete THREAD_ID --action-taken "..." --json`；OpenClaw 插件：`twinbox_queue_complete`（`thread_id`，可选 `action_taken`） |
| 恢复一个 dismissed/completed 线程 | `twinbox queue restore THREAD_ID --json` |
| 查看当前调度配置 | `twinbox schedule list --json` 或 OpenClaw 工具 `twinbox_schedule_list` |
| 修改 daily/weekly/nightly 调度时间 | `twinbox schedule update JOB_NAME --cron "30 9 * * *" --json` 或 OpenClaw 工具 `twinbox_schedule_update` |
| 恢复某个调度到默认时间 | `twinbox schedule reset JOB_NAME --json` 或 OpenClaw 工具 `twinbox_schedule_reset` |
| 启用某个后台调度（创建 OpenClaw cron job） | `twinbox schedule enable JOB_NAME --json` 或 OpenClaw 工具 `twinbox_schedule_enable` |
| 禁用某个后台调度（删除 OpenClaw cron job） | `twinbox schedule disable JOB_NAME --json` 或 OpenClaw 工具 `twinbox_schedule_disable` |
| "某个事情进展如何" / progress on a topic | `twinbox task progress QUERY --json` |
| Mailbox status / env diagnosis | `twinbox task mailbox-status --json` |
| Auto-detect email server config | `twinbox mailbox detect EMAIL --json` |
| 查看当前单配置文件 | `twinbox config show --json` |
| 配置邮箱凭据（自动探测或显式主机参数，写入 `twinbox.json`）| `twinbox mailbox setup --email EMAIL --json` 或 `twinbox config mailbox-set --email EMAIL --json`（密码从 `TWINBOX_SETUP_IMAP_PASS` 注入）或 OpenClaw 工具 `twinbox_mailbox_setup` |
| 配置 LLM API（写入 `twinbox.json`）| `twinbox config set-llm --provider openai|anthropic --model MODEL --api-url URL --json`（key 从 `TWINBOX_SETUP_API_KEY` 注入；必须显式传 model 和 api-url，Twinbox 不再内置默认 LLM 配置）或 OpenClaw 工具 `twinbox_config_set_llm`；与 OpenClaw 默认模型一致时可 `twinbox config import-llm-from-openclaw --json`（需 `openclaw.json` 内联 `apiKey`）或插件 `twinbox_config_import_llm_from_openclaw` |
| 配置 Twinbox 偏好（含 CC 降权） | `twinbox config set-preferences --cc-downweight on|off --json` |
| 导入会议纪要/项目台账等外部材料进入周报 | `twinbox context import-material FILE --intent reference`（随后跑 `twinbox-orchestrate run --phase 4` 或等常规调度） |
| 自定义周报模板（标题/章节顺序/措辞） | 先展示 `config/weekly-template.md`，再把用户确认的新模板用 `twinbox context import-material FILE --intent template_hint` 导入 |
| 配置 Twinbox integration 默认值 | `twinbox config integration-set --use-fragment yes|no [--fragment-path PATH] --json` |
| 配置 OpenClaw 默认值 | `twinbox config openclaw-set [--home PATH] [--bin NAME] [--strict|--no-strict] [--sync-env|--no-sync-env] [--restart-gateway|--no-restart-gateway] --json` |
| OpenClaw 安装总向导（唯一公开向导入口；OpenClaw 风格显式步骤向导：Security（默认 No、须显式选 Yes 才继续）、Quickstart/Manual、Mailbox、LLM、Twinbox tools integration、Apply setup + 更强 handoff；已有 Mailbox/LLM 值会先进入 `Existing config detected` / `Config handling`；LLM 步可选 **Import from OpenClaw**（读 OpenClaw home 下 `openclaw.json` 默认模型，约束同 `config import-llm-from-openclaw`）；手动配置时覆盖输入顺序为 `API URL -> API key -> Model ID`；选择沿用现有 LLM 配置继续时，会重新解析校验当前配置并同步 onboarding 状态） | `twinbox onboard openclaw --json` |
| OpenClaw 宿主接线高级入口（roots + `openclaw.json` + 按 OS/CPU 的 `himalaya` 检查/内置 Linux 解压 + SKILL 真源在 state root + 对 `~/.openclaw/.../SKILL.md` 软链或复制 + 可选重启 Gateway）| `twinbox deploy openclaw --json`（高级/脚本化入口；`--dry-run`；`--no-restart`；`--no-env-sync`；`--strict`；可选 `--fragment` / `--no-fragment` 合并 `openclaw-skill/openclaw.fragment.json`） |
| 撤销上述宿主接线（不删 `~/.twinbox`；非全量卸载）| `twinbox deploy openclaw --rollback --json`（可选 `--remove-config` 删 `~/.config/twinbox`） |
| Weekly brief lookup | `twinbox task weekly --json` |
| Manage semantic routing rules / "以后别把这类邮件派给我" | `twinbox rule list --json` / `twinbox rule add --rule-json ...` |
| Test a routing rule against recent threads | `twinbox rule test --rule-id RULE_ID --json` |
| Start onboarding flow | `twinbox onboarding start --json`（人类可读输出会以 “Phase 2 of 2” 继续旅程） |
| Check onboarding progress | `twinbox onboarding status --json`（人类可读输出会以 “Phase 2 of 2” 继续旅程） |
| Advance onboarding to next stage | `twinbox onboarding next --json`（人类可读输出会以 “Phase 2 of 2” 继续旅程） |
| User已用自然语言答完当前阶段（画像 / 材料 / 规则 / 推送等） | 先简短确认，再 **`twinbox onboarding next --json`**（若是画像阶段，可加 `--profile-notes "用户画像摘要"`、`--calibration-notes "本周关注/忽略/重点摘要"`，以及在用户明确“CC 也是主要工作”时加 `--cc-downweight off`），然后根据 stdout 总结 `completed_stage`、`current_stage`、下一段 `prompt`（不可只调工具无正文） |
| 后台 JSON-RPC daemon（省 Python 冷启动；可选） | `twinbox daemon start` / `stop` / `restart`；`twinbox daemon status --json`（含 `cache_stats`）。Socket：`$TWINBOX_STATE_ROOT/run/daemon.sock`。Go：`cmd/twinbox-go`（RPC 失败则 `exec` Python）；`twinbox-go install --archive …` 可从本地路径或 HTTP URL 解压 vendor tarball |
| 多邮箱 profile（共享 vendor、独立 state） | `twinbox --profile NAME …`（`TWINBOX_STATE_ROOT=~/.twinbox/profiles/NAME/state`，`TWINBOX_HOME=~/.twinbox`） |
| Phase loading（Python 入口） | `twinbox loading phase1` … `phase4`（全部走 Python；`scripts/phase1_loading.sh` / `phase4_loading.sh` 仅保留兼容 shim，phase1/4 仍使用 himalaya CLI 传输） |
| 把 `twinbox_core` 同步到 vendor（宿主 PYTHONPATH） | `twinbox vendor install`；`twinbox vendor status --json`（`integrity_ok` / `file_count`）。装好后：`PYTHONPATH="$TWINBOX_HOME/vendor"` 或 `…/state/vendor`（无 profile 时二者常相同）+ `python3 -m twinbox_core.task_cli …` |
| Subscribe to push notifications | `twinbox push subscribe SESSION_ID --json` |
| List push subscriptions | `twinbox push list --json` |
| Inspect one exact thread / “把这个线程内容返回给我看看” / “先读这个线程” | `twinbox thread inspect THREAD_ID --json` 或 OpenClaw 工具 `twinbox_thread_inspect` 且传 `thread_id` |
| Explain why a thread is urgent / pending | `twinbox thread explain THREAD_ID --json` |
| Daily digest | `twinbox digest daily --json`（人类可读模式为 Markdown；稳定消费优先 `--json`） |
| Weekly brief | `twinbox digest weekly --json`（人类可读模式为 Markdown，按默认 `config/weekly-template.md` 或最新 `template_hint` 的标题/章节顺序渲染；若已有 `runtime/validation/phase-4/daily-ledger/` snapshots，会把本周早些时候已退出 action surface 的线程轨迹补回 `important_changes`；仍不是 daily 自动累计；稳定消费优先 `--json`） |
| Suggest next actions | `twinbox action suggest --json` |
| Materialize one suggested action | `twinbox action materialize ACTION_ID --json` |
| Review items | `twinbox review list --json` / `twinbox review show REVIEW_ID --json` |
| Refresh hourly/daytime projection | `twinbox-orchestrate schedule --job daytime-sync --format json` |
| Refresh full nightly/weekly pipeline | `twinbox-orchestrate schedule --job nightly-full --format json` |

## Task Routing Rules

- When the user confirms a thread is **done** or **dismissed**, you must persist queue state: run `twinbox queue complete` / `queue dismiss` with `--json`, or call OpenClaw tools `twinbox_queue_complete` / `twinbox_queue_dismiss`. Resolve `thread_id` from `task todo`, `task latest-mail`, or `thread inspect` — freeform weekly-brief lines alone are not thread keys.
- The file `runtime/context/user-queue-state.yaml` is **created on the first successful** `queue complete` or `queue dismiss`; absence before that is normal.
- Run the command first (`--json`), then summarize stdout in plain text for the user
- Prefer `twinbox task ...` for common user prompts; these are thin wrappers, not a second pipeline
- For the latest mail situation (including casual Chinese variants), use `twinbox task latest-mail --json` first; do not start with `preflight` unless connectivity is the explicit problem. If the user explicitly asks for "未读" (unread), pass `--unread-only` to the command or `unread_only: true` to the tool.
- If the user wants one exact thread's content/details/status, prefer `twinbox thread inspect THREAD_ID --json` or `twinbox_thread_inspect`; do not use `task progress` unless the request is fuzzy/topic-based.
- If `activity-pulse.json` is missing or stale, run `twinbox-orchestrate schedule --job daytime-sync` and explain the refresh
- `daytime-sync` now enters through the incremental Phase 1 entrypoint (`scripts/phase1_incremental.sh`) before Phase 3/4 daytime projection
- The incremental Phase 1 path uses UID watermarks and automatically falls back to the existing full loader when `UIDVALIDITY` changes
- Default schedule definitions now live in `config/schedules.yaml`; `twinbox schedule update/reset` writes `runtime/context/schedule-overrides.yaml` and then attempts to sync the matching Twinbox OpenClaw cron job via `openclaw cron list/edit/add`
- If Gateway access fails, the command still preserves the runtime override and exposes `platform_sync.status=error` in JSON output
- For schedule prompts, prefer native OpenClaw tools `twinbox_schedule_list` / `twinbox_schedule_update` / `twinbox_schedule_reset` / `twinbox_schedule_enable` / `twinbox_schedule_disable` over generic `cron` or workspace search
- For onboarding mailbox setup, prefer native OpenClaw tool `twinbox_mailbox_setup` (passes password via env, never CLI args)
- For onboarding LLM API config, prefer native OpenClaw tool `twinbox_config_set_llm` (passes api_key via env)
- Stay read-only unless the user explicitly asks for draft/action generation
- **Never end a task turn with only file reads and no text answer.** A turn with `assistant.content=[]` or no text is a failure — always produce real command output followed by a summary

## Hosted Defaults

- Prefer a dedicated `twinbox` agent/session for Twinbox work; keep `main` for general chat
- After skill or env changes, use a fresh Twinbox session; `skillsSnapshot` can freeze old injection results
- Hosted env should come from `skills.entries.twinbox.env`; `state root/twinbox.json` is the Twinbox config source, and any legacy `.env` is only a migration fallback
- If `plugin-twinbox-task` is enabled, prefer an absolute `twinboxBin` pointing to `scripts/twinbox`; if unset, keep `cwd` accurate so the plugin can auto-detect `<cwd>/scripts/twinbox` instead of relying on Gateway PATH
- Treat OpenClaw schedule execution as a Twinbox-managed bridge cron concern; current default definitions come from `config/schedules.yaml`, not skill metadata
- The currently verified refresh path is `openclaw cron -> system-event -> host bridge/poller -> twinbox-orchestrate schedule --job ...`

## Guardrails

- Stay read-only by default (mailbox IMAP remains read-only in Phase 1–4)
- `queue complete` / `queue dismiss` only update **local** Twinbox queue visibility (`user-queue-state.yaml`); use them when the user asks to stop reminders for a **specific thread** they name or confirm
- Do not send, delete, archive, or mutate mailbox state unless the user explicitly requests it and the runtime supports it
- Do not claim OpenClaw auto-imports schedule metadata; current verified schedule setup comes from `twinbox schedule update/reset` syncing bridge cron jobs
- Do not treat `openclaw skills info twinbox = Ready` as proof that the current session prompt already contains `twinbox`
- Do not claim the platform has automatically run `preflightCommand` unless you have evidence from a real execution path

## Fast Checks

- `twinbox task mailbox-status --json`
- `twinbox task latest-mail --json`
- `twinbox task todo --json`
- `twinbox queue dismiss THREAD_ID --reason "已处理" --json`
- `twinbox queue complete THREAD_ID --action-taken "已归档" --json`
- `twinbox queue restore THREAD_ID --json`
- `twinbox schedule list --json`
- `twinbox schedule update daily-refresh --cron "30 9 * * *" --json`
- `twinbox schedule reset daily-refresh --json`
- `twinbox task progress QUERY --json`
- `twinbox digest pulse --json`（人类可读模式为 Markdown；稳定消费优先 `--json`）
- `twinbox-orchestrate roots`
- `twinbox daemon status --json`（daemon 未启用时 `status=stopped` 属正常）
- `twinbox-orchestrate contract --phase 4`
- `twinbox-orchestrate schedule --job daytime-sync --format json`
- `twinbox-orchestrate run --phase 1`
- `twinbox-orchestrate run --phase 4`

## Runtime Notes

- `mailbox-connected` means read-only IMAP preflight succeeded
- `status=warn` with `smtp_skipped_read_only` is acceptable for preflight
- OpenClaw-native deployments should inject mailbox env into process env via `skills.entries.twinbox.env`; `state root/twinbox.json` is the Twinbox config source, and any legacy `.env` is only a migration fallback
- If Twinbox stops appearing in answers after a deploy, check env gating first, then session-level `skillsSnapshot`
- If Twinbox commands fail, first verify env, mounted repo root, `runtime/bin/himalaya` (on Linux x86_64/aarch64, twinbox can extract a bundled `himalaya` there on first preflight), and Python dependencies on the OpenClaw host

**Claude Code skill (deeper repo workflow):** [`.claude/skills/twinbox/SKILL.md`](.claude/skills/twinbox/SKILL.md)
