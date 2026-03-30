---
name: twinbox
description: >-
  Twinbox mailbox skill. REQUIRED behavior: after running any twinbox CLI
  command, always produce a text summary for the user — never stop with tool
  calls alone; a turn with no text reply is a failure. If a command fails
  (e.g. missing activity-pulse.json), explain why and suggest the fix (run
  twinbox-orchestrate schedule --job daytime-sync). OpenClaw Phase 2: when
  the user finishes answering profile_setup in chat, you MUST call
  twinbox_onboarding_advance in the same turn with profile_notes and
  calibration_notes derived from their message, then write visible text —
  never leave the stage stuck and never end tool-only. At routing_rules,
  persist rules with twinbox_rule_add then advance in the same turn. Never say you will
  import material or advance onboarding without calling the matching tool in
  the same turn (some hosted models often stop after the sentence and drop
  the chain). Use for: email preflight,
  latest-mail, queue triage, onboarding (start/status/next), weekly digest,
  thread progress, schedule management, and OpenClaw deploy diagnostics via
  `twinbox` / `twinbox-orchestrate`.
metadata: {"openclaw":{"requires":{"env":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"]},"primaryEnv":"IMAP_LOGIN","login":{"mode":"password-env","runtimeRequiredEnv":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"],"optionalDefaults":{"MAIL_ACCOUNT_NAME":"myTwinbox","MAIL_DISPLAY_NAME":"{MAIL_ACCOUNT_NAME}","IMAP_ENCRYPTION":"tls","SMTP_ENCRYPTION":"tls"},"stages":["unconfigured","validated","mailbox-connected"],"preflightCommand":"twinbox mailbox preflight --json"}}}
---

# twinbox

Use this skill for Twinbox mailbox onboarding, read-only preflight checks, latest-mail summaries, queue triage, thread progress lookup, weekly digest lookup, queue refresh, and deployment debugging in OpenClaw-managed environments.

## Session and verification (mechanism, not IDE-specific)

Twinbox mail state is produced by **`twinbox` / `twinbox-orchestrate` on the OpenClaw host** and consumed inside a **`twinbox` agent session** (tool policy + session history + Gateway). Regressions such as empty assistant payloads, “read SKILL only”, or silent turns are addressed by **session design and test procedure** (fresh session when needed, bootstrap turn, split long suites, optional **`plugin-twinbox-task`** tools), documented in `integrations/openclaw/prompt-test.md` and `scripts/run_openclaw_prompt_tests.py` — not by relabeling the client app.

Known OpenClaw limitation (confirmed 2026-03-27 on some gateway-hosted models): OpenClaw injects this skill's **`description`** into the system prompt, but the rest of `~/.openclaw/skills/twinbox/SKILL.md` is visible only if the agent explicitly reads the file. On those setups, turns that call tools can stop immediately after the tool call and return `payloads=[]`, `assistant.content=[]`, or a short stub such as `让我执行命令：`. **Plugin hosts:** use native **`twinbox_onboarding_*`** tools when `plugin-twinbox-task` is loaded; otherwise `twinbox onboarding …` may go through generic `exec` and show the same empty bubble.

**If the UI shows nothing after you answered `profile_setup` in plain language:** the stage has **not** advanced until the host runs **`twinbox_onboarding_advance`** (plugin) or **`twinbox openclaw onboarding-advance --profile-notes "…" --calibration-notes "…"`** with your text. Send one follow-up message that tells the agent to run **`twinbox_onboarding_advance`** with `profile_notes` + `calibration_notes` copied from your previous reply, **then** summarize the JSON; or run the CLI yourself in a shell and paste stdout.

Recommended hosted workaround: start a **fresh `twinbox` session**, send one **bootstrap** turn that tells the agent to read `~/.openclaw/skills/twinbox/SKILL.md` first and then run the exact `twinbox ... --json` command in the same turn, and treat host-shell `twinbox ... --json` output as the source of truth for machine-readable verification if the session still returns empty payloads. Prefer native plugin tools where they exist; use the bootstrap path when tools are unavailable.

## Turn contract

For **all** twinbox command executions (mail, queue, digest, onboarding, deploy, schedule, rule, etc.): run the matching `twinbox` command with `--json`, then reply with a text summary. Never end with only tool calls and no text response. A turn with `payloads=[]` or `assistant.content=[]` is always a failure.

### No broken tool chains (critical on weak tool models)

These models often **stop after narration** (“现在导入到 Twinbox:”“下一步执行…”) **without** invoking the next tool — treat that as a **hard failure** to prevent.

- **Forbidden:** Ending an assistant message with intent to run a Twinbox action **without** having invoked the corresponding tool in the **same** assistant turn (or the **immediately following** assistant turn if the host splits tool output from text).
- **After `exec` / shell writes a file** (e.g. `/tmp/...md`): the **same turn** must continue with **`twinbox_context_import_material`** (plugin) or **`twinbox context import-material PATH --intent reference|template_hint`** — do **not** stop after “文件已创建”.
- **After import-material** during onboarding: if the material step is complete, **same or next turn** call **`twinbox_onboarding_advance`** (when appropriate) and summarize **`completed_stage` / `current_stage` / `prompt`** in visible text.
- **At `routing_rules`:** when the user describes a filter (or says **skip** / **跳过** with no rules), **same turn:** **`twinbox_rule_add`** with `rule_json` built from their intent (or **no** rule add if they truly skip) → **`twinbox_onboarding_advance`** → **visible summary**. Do not stop after asking “要不要配规则” once they already answered.
- **Canonical order:** write or obtain file path → **import-material** → (if needed) **onboarding_advance** → **visible summary**. Skipping the middle link is the usual failure mode.

### Onboarding: advancing after the user replies (critical)

Stages such as `profile_setup`, `material_import`, `routing_rules`, and `push_subscription` are **dialogue-first**: you collect answers in chat, but **nothing persists and the stage does not advance** until the Twinbox host runs an **advance** command. **OpenClaw with `plugin-twinbox-task`:** prefer **`twinbox_onboarding_advance`** (wraps `twinbox openclaw onboarding-advance`). **Shell / no plugin:** **`twinbox onboarding next --json`** with the same optional flags is equivalent for advancing state. Do not tell the user they must type a command name — **you** must invoke the tool or CLI once their answer is ready.

#### Near-automatic profile_setup (agent rules — prioritize this)

When **`current_stage` is `profile_setup`** and the user’s message contains their substantive answer (role, habits, weekly focus, what to ignore, CC handling, etc.):

1. **Same assistant turn (preferred):** call **`twinbox_onboarding_advance`** with **`profile_notes`** and **`calibration_notes`** — concise summaries of what they said (not a second LLM rewrite pass; you are the summarizer). Use **`cc_downweight`** `on`/`off` only when they clearly stated CC vs primary-inbox preference.
2. **Immediately after the tool returns, same turn:** write a **visible** reply summarizing **`completed_stage`**, **`current_stage`**, and the next **`prompt`** (quote or paraphrase). **Tool-only turns are always a failure** when the assistant omits visible text after tools (empty bubble).
3. **If the platform cannot attach text after tools in one response:** in the **very next** assistant message, call **`twinbox_onboarding_advance`** if not already done, then summarize — **do not** wait for the user to ask for “advance” or “next command.”

#### Near-automatic routing_rules (agent rules)

When **`current_stage` is `routing_rules`** and the user message is a **concrete rule request** (e.g. 自动归档/降权某类邮件) or an explicit **skip**:

1. **Same turn:** build a **`rule_json`** string (schema: see `config/routing-rules.yaml` examples — `id`, `name`, `active`, `conditions`, `actions` with `set_state` / `add_tags` / `skip_phase4` as needed). Call **`twinbox_rule_add`**, then **`twinbox_onboarding_advance`** (no profile fields needed). If the user clearly skips rules, you may call **`twinbox_onboarding_advance`** only.
2. **Immediately after:** visible text with **`completed_stage`**, **`current_stage`**, next **`prompt`**. **Never** end with tool-only or with “下一步” narration and no tools.

**Recovery if the UI is empty** after the user sent a rule line: **`twinbox_rule_add`** (from their last message) → **`twinbox_onboarding_advance`** → paste summary; or run **`twinbox onboarding next --json`** on the host if plugin unavailable.

**Persistence details for profile_setup:** CLI flags **`--profile-notes`** / **`--calibration-notes`** / **`--cc-downweight`** map to `runtime/context/human-context.yaml` (`profile_notes` / `calibration`) plus `twinbox.json.preferences.cc_downweight.enabled`. Phase 2/3 **and Phase 4** **`context-pack.json`** expose these as `human_context.onboarding_profile_notes` / `human_context.calibration_notes`. Legacy `manual-facts.yaml` / `manual-habits.yaml` / `instance-calibration-notes.md` / onboarding `profile_data.*` migrate on first read; afterward the unified file is authoritative. For stages without these flags, use `twinbox context upsert-fact` / `profile-set` if you need durable prose. For **material_import**, show `config/weekly-template.md` first; if the user wants different sections, turn that into Markdown and import with **`twinbox_context_import_material`** (plugin) or `twinbox context import-material FILE --intent template_hint`, then rerun Phase 4 or wait for weekly refresh — **same turn as the file exists**, no “下一步再导入”.

**Recovery if the UI went idle** after the user sent their profile (no assistant text, empty bubble): (1) **`twinbox_onboarding_advance`** with `profile_notes` / `calibration_notes` from the user’s **last** message; (2) **`twinbox_onboarding_status`** then **`twinbox_onboarding_advance`** (or `twinbox onboarding status --json` then `twinbox onboarding next --json` with the same profile flags). If the Gateway still drops payloads, run **`twinbox openclaw onboarding-advance --profile-notes '…' --calibration-notes '…' --json`** on the **host shell** and paste stdout into chat.

**Session:** prefer a **dedicated `twinbox` agent** for onboarding handoff — not `main` — so skill injection, tools, and `integrations/openclaw/DEPLOY.md` match.

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
- **Full uninstall** of Twinbox on a host: stop daemon / OpenClaw bridge, remove CLI binaries, delete state + config pointers, scrub shell and OpenClaw env (see **Full uninstall (CLI, state, env)** below)

## Full uninstall (CLI, state, env)

**Not** the same as `deploy openclaw --rollback` (that keeps `~/.twinbox` and any `twinbox` on `PATH`). Do this **while `twinbox` still runs**: `daemon stop` → `deploy openclaw --rollback [--remove-config]` → `host bridge remove` / `schedule disable JOB` if still needed.

**Binaries:** `pip uninstall -y twinbox-core` (removes `twinbox`, `twinbox-orchestrate`, `twinbox-eval-phase4`); delete any other `twinbox` on `PATH` (e.g. `~/.local/bin`, `/usr/local/bin`); optional repo junk: `dist/twinbox*`, `cmd/twinbox-go/twinbox`.

**Data, OpenClaw, env:** `rm -rf ~/.twinbox` (destructive—backup first); remove stale `~/.config/twinbox/*` if present; delete `~/.openclaw/skills/twinbox`, drop `plugin-twinbox-task` per `integrations/openclaw/DEPLOY.md`, then `openclaw gateway restart`. Strip **`TWINBOX_*`**, **`TWINBOX_SETUP_*`**, and mailbox vars from this skill’s `metadata.openclaw.requires.env` wherever set (shell, systemd, OpenClaw skill env, CI). New shell: `command -v twinbox` empty.

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
| 导入会议纪要/项目台账等外部材料进入周报 | OpenClaw 有插件时优先 **`twinbox_context_import_material`**（`source_path` + `intent`）；否则 `twinbox context import-material FILE --intent reference`（随后跑 `twinbox-orchestrate run --phase 4` 或等常规调度） |
| 自定义周报模板（标题/章节顺序/措辞） | 先展示 `config/weekly-template.md`，再把用户确认的新模板用 **`twinbox_context_import_material`**（`intent=template_hint`）或 `twinbox context import-material FILE --intent template_hint` 导入 |
| 配置 Twinbox integration 默认值 | `twinbox config integration-set --use-fragment yes|no [--fragment-path PATH] --json` |
| 配置 OpenClaw 默认值 | `twinbox config openclaw-set [--home PATH] [--bin NAME] [--strict|--no-strict] [--sync-env|--no-sync-env] [--restart-gateway|--no-restart-gateway] --json` |
| OpenClaw 安装总向导（唯一公开向导入口；**Apply setup 后默认完成**：OpenClaw 合并 + plugin/tools 可观测性 + **vendor-safe bridge user timer 安装 + health dry-run**；`phase2_ready=true` 才 handoff Phase 2；逃生口 `--skip-bridge`；部署成功后默认尝试 **daemon start**，`--no-start-daemon` 跳过） | `twinbox onboard openclaw [--skip-bridge] [--no-start-daemon] --json` |
| OpenClaw 宿主接线高级入口（与 onboard 共享同一套 prerequisite bundle；默认安装 bridge；成功后默认 **daemon start**，`--no-start-daemon` 跳过）| `twinbox deploy openclaw --json`（`--dry-run`；`--no-restart`；`--no-env-sync`；`--strict`；`--skip-bridge`；`--twinbox-bin`；`--no-start-daemon`；可选 `--fragment` / `--no-fragment`） |
| 撤销上述宿主接线（不删 `~/.twinbox`；**同时移除 bridge user units**）| `twinbox deploy openclaw --rollback --json`（可选 `--remove-config`） |
| Vendor-safe OpenClaw bridge（systemd user 单元只调用已安装 `twinbox`，不依赖 repo `scripts/`） | `twinbox host bridge install|remove|status|poll [--dry-run] [--openclaw-bin …]` |
| OpenClaw 内 Phase 2 onboarding 与上下文材料（对应 CLI：`twinbox openclaw …` / `twinbox context …`） | 插件：`twinbox_context_import_material` / `twinbox_onboarding_start` / `twinbox_onboarding_status` / `twinbox_onboarding_advance` / `twinbox_onboarding_confirm_push` |
| Weekly brief lookup | `twinbox task weekly --json` |
| Manage semantic routing rules / "以后别把这类邮件派给我" | `twinbox rule list --json` / `twinbox rule add --rule-json ...` |
| Test a routing rule against recent threads | `twinbox rule test --rule-id RULE_ID --json` |
| Start onboarding flow | `twinbox onboarding start --json`（人类可读输出会以 “Phase 2 of 2” 继续旅程） |
| Check onboarding progress | `twinbox onboarding status --json`（人类可读输出会以 “Phase 2 of 2” 继续旅程） |
| Advance onboarding to next stage | `twinbox onboarding next --json`（人类可读输出会以 “Phase 2 of 2” 继续旅程） |
| User已用自然语言答完当前阶段（画像 / 材料 / 规则 / 推送等） | OpenClaw 有插件时：**同轮**先 **`twinbox_onboarding_advance`**（画像阶段必带 `profile_notes` / `calibration_notes` 要点）；否则 **`twinbox onboarding next --json`**（画像同上，可加 `--cc-downweight off` 若用户明确 CC 为主要工作）。然后**必须**根据返回 JSON 总结 `completed_stage`、`current_stage`、下一段 `prompt`（不可只调工具无正文） |
| 后台 JSON-RPC daemon（省 Python 冷启动；可选） | `daemon start` / `onboard`·`deploy` 触发的拉起。`twinbox daemon status --json`（含 `cache_stats` 等）。Socket：`$TWINBOX_STATE_ROOT/run/daemon.sock`。Go：交付默认可为 `twinbox`（**dial 失败**时静默跑一次 `daemon start` 再重试 RPC；`TWINBOX_NO_LAZY_DAEMON=1` 关闭）；仍失败则 `exec` Python；vendor 会校验 `MANIFEST.json`）；`twinbox install --archive …` 解压到 `vendor/` 并写 `code-root`（开发可用 `TWINBOX_CODE_ROOT` 覆盖） |
| 多邮箱 profile（共享 vendor、独立 state） | `twinbox --profile NAME …`（`TWINBOX_STATE_ROOT=~/.twinbox/profiles/NAME/state`，`TWINBOX_HOME=~/.twinbox`） |
| Phase loading（Python 入口） | `twinbox loading phase1` … `phase4`（全部走 Python；`scripts/phase1_loading.sh` / `phase4_loading.sh` 仅保留兼容 shim，phase1/4 仍使用 himalaya CLI 传输） |
| 把 `twinbox_core` 同步到 vendor（宿主 PYTHONPATH） | `twinbox vendor install`；`twinbox vendor status --json`（`integrity_ok` / `file_count`）。装好后：`PYTHONPATH="$TWINBOX_HOME/vendor"` 或 `…/state/vendor`（无 profile 时二者常相同）+ `python3 -m twinbox_core.task_cli …` |
| Subscribe to push（**daily / weekly 可分别开关**；首次开 daily 会尝试把 `daily-refresh` 默认改为 hourly 且无既有 override 时） | `twinbox push subscribe SESSION_ID [--daily on|off] [--weekly on|off] --json` |
| 调整已有订阅的 cadence | `twinbox push configure SESSION_TARGET --daily on|off --weekly on|off --json` |
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
| **完全卸载** | 见上节 **Full uninstall**（rollback → 删 pip/二进制 → 删 `~/.twinbox` → skill/plugin → 清 env） |

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
- For onboarding after mailbox/LLM, prefer `twinbox_onboarding_start` / `twinbox_onboarding_status` / `twinbox_onboarding_advance`; **push_subscription** 用 `twinbox_onboarding_confirm_push`（事务性写订阅 + schedule ownership），避免仅依赖 `onboarding next` 的占位文案
- After the user answers **profile_setup** in natural language, **do not** end the turn without **`twinbox_onboarding_advance`** (or equivalent `onboarding next` / `openclaw onboarding-advance`) **and** a visible summary — the user should not need to name the CLI
- After **writing or staging a file** for Twinbox (e.g. `exec` to `/tmp/...`), **do not** end the turn without **`twinbox_context_import_material`** (or `twinbox context import-material …`) **and** a visible summary — never stop at “现在导入…”
- Prefer **`twinbox_context_import_material`** over generic shell for the same path so the model sees a **named tool** and is less likely to drop the chain
- Stay read-only unless the user explicitly asks for draft/action generation
- **Never end a task turn with only file reads and no text answer.** A turn with `assistant.content=[]` or no text is a failure — always produce real command output followed by a summary

## Hosted Defaults

- Prefer a dedicated `twinbox` agent/session for Twinbox work; keep `main` for general chat
- After skill or env changes, use a fresh Twinbox session; `skillsSnapshot` can freeze old injection results
- Hosted env should come from `skills.entries.twinbox.env`; `state root/twinbox.json` is the Twinbox config source, and any legacy `.env` is only a migration fallback
- If `plugin-twinbox-task` is enabled, prefer an absolute `twinboxBin` pointing to `scripts/twinbox`; if unset, keep `cwd` accurate so the plugin can auto-detect `<cwd>/scripts/twinbox` instead of relying on Gateway PATH
- Treat OpenClaw schedule execution as a Twinbox-managed bridge cron concern; current default definitions come from `config/schedules.yaml`, not skill metadata
- Bridge poller 默认路径：`systemd user timer` → `twinbox host bridge poll` → `openclaw gateway call cron.*` → `twinbox-orchestrate schedule --job …`（vendor 安装不依赖 `scripts/twinbox_openclaw_bridge_poll.sh`）

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
