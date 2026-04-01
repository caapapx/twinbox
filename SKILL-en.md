---
name: twinbox
description: >-
  Twinbox mailbox skill. CRITICAL: always call the matching plugin tool
  FIRST, then write a text summary after it returns. Never narrate
  "let me run", "need to sync first", or Chinese variants like 「让我执行」
  without calling a tool in the same turn — that is always a failure.
  Never duplicate the same sentence or near-duplicate paragraphs in one
  assistant message (no repeated "I'll sync then check" boilerplate); at most
  one short lead-in, then the tool call.   If no twinbox_* tools are available
  in this session, output one line saying the plugin or twinbox agent is
  required — do not fabricate a sync narrative.
  Never tell the user you will "sync mail data first, then show latest" (or
  Chinese variants like 先同步邮件数据，然后查看最新邮件) — any required sync
  runs inside twinbox_latest_mail; saying this in prose is wrong.
  For latest mail / inbox / 最新邮件: call twinbox_latest_mail immediately;
  it auto-runs daytime-sync inside one tool call when data is missing — do
  not loop in prose. At push_subscription: twinbox_push_confirm_onboarding
  (no session param). At routing_rules: twinbox_onboarding_finish_routing_rules.
  At profile_setup: twinbox_onboarding_advance with profile_notes +
  calibration_notes in the same turn. Never end a turn with only text when
  the user asked for mail, todo, digest, or onboarding action.
metadata: {"openclaw":{"requires":{"env":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"]},"primaryEnv":"IMAP_LOGIN","login":{"mode":"password-env","runtimeRequiredEnv":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"],"optionalDefaults":{"MAIL_ACCOUNT_NAME":"myTwinbox","MAIL_DISPLAY_NAME":"{MAIL_ACCOUNT_NAME}","IMAP_ENCRYPTION":"tls","SMTP_ENCRYPTION":"tls"},"stages":["unconfigured","validated","mailbox-connected"],"preflightCommand":"twinbox mailbox preflight --json"}}}
---

# twinbox

Use this skill for Twinbox mailbox onboarding, read-only preflight checks, latest-mail summaries, queue triage, thread progress lookup, weekly digest lookup, queue refresh, and deployment debugging in OpenClaw-managed environments.

## Session and verification (mechanism, not IDE-specific)

Twinbox mail state is produced by **`twinbox` / `twinbox-orchestrate` on the OpenClaw host** and consumed inside a **`twinbox` agent session** (tool policy + session history + Gateway). Regressions such as empty assistant payloads, "read SKILL only", or silent turns are addressed by **session design and test procedure** (fresh session when needed, bootstrap turn, split long suites, optional **`plugin-twinbox-task`** tools), documented in `integrations/openclaw/prompt-test.md` and `scripts/run_openclaw_prompt_tests.py` — not by relabeling the client app.

Known OpenClaw limitation (confirmed 2026-03-27 on some gateway-hosted models): OpenClaw injects this skill's **`description`** into the system prompt, but the rest of `~/.openclaw/skills/twinbox/SKILL.md` is visible only if the agent explicitly reads the file. On those setups, turns that call tools can stop immediately after the tool call and return `payloads=[]`, `assistant.content=[]`, or a short stub such as "Let me run the command:". **Plugin hosts:** use native **`twinbox_onboarding_*`** tools when `plugin-twinbox-task` is loaded; otherwise `twinbox onboarding …` may go through generic `exec` and show the same empty bubble.

**If the UI shows nothing after you answered `profile_setup` in plain language:** the stage has **not** advanced until the host runs **`twinbox_onboarding_advance`** (plugin) or **`twinbox openclaw onboarding-advance --profile-notes "…" --calibration-notes "…"`** with your text. Send one follow-up message that tells the agent to run **`twinbox_onboarding_advance`** with `profile_notes` + `calibration_notes` copied from your previous reply, **then** summarize the JSON; or run the CLI yourself in a shell and paste stdout.

Recommended hosted workaround: start a **fresh `twinbox` session**, send one **bootstrap** turn: read `~/.openclaw/skills/twinbox/SKILL.md`, then in the **same** turn call **`twinbox_onboarding_status`** or run **`twinbox onboarding status --json`** (lightweight; after TTY onboard often `completed`). If not completed, call **`twinbox_onboarding_start`** / **`twinbox onboarding start --json`**. Optionally use **`twinbox_latest_mail`** first for a heavier mail-pipeline smoke test (daytime-sync). Treat host-shell `twinbox ... --json` as source of truth if payloads stay empty. Prefer native plugin tools.

**Feishu / Telegram / other channels for digests:** in **that** session, ask the agent to bind push here using **`twinbox_onboarding_confirm_push`** with **`session_target`**, or **`twinbox push subscribe <session> --daily on --weekly on`**. The TTY wizard outro includes a second copy-paste line for this.

## Turn contract

For **all** twinbox command executions (mail, queue, digest, onboarding, deploy, schedule, rule, etc.): run the matching `twinbox` command with `--json`, then reply with a text summary. Never end with only tool calls and no text response. A turn with `payloads=[]` or `assistant.content=[]` is always a failure.

### No broken tool chains (critical on weak tool models)

These models often **stop after narration** ("Now importing to Twinbox:" / "Next, I will run…") **without** invoking the next tool — treat that as a **hard failure** to prevent.

- **Forbidden:** Ending an assistant message with intent to run a Twinbox action **without** having invoked the corresponding tool in the **same** assistant turn (or the **immediately following** assistant turn if the host splits tool output from text).
- **After `exec` / shell writes a file** (e.g. `/tmp/...md`): the **same turn** must continue with **`twinbox_context_import_material`** (plugin) or **`twinbox context import-material PATH --intent reference|template_hint`** — do **not** stop after "File created".
- **After import-material** during onboarding: if the material step is complete, **same or next turn** call **`twinbox_onboarding_advance`** (when appropriate) and summarize **`completed_stage` / `current_stage` / `prompt`** in visible text.
- **At `routing_rules`:** when the user describes a filter (or says **skip**), **same turn:** prefer **`twinbox_onboarding_finish_routing_rules`** (`rule_json` or `skip_rules: true`) — one plugin execution does add + advance; fallback **`twinbox_rule_add`** then **`twinbox_onboarding_advance`** → **visible summary**. Do not stop after asking "Do you want to configure rules?" once they already answered.
- **At `push_subscription`:** when the user says **confirm** (or agrees to daily/weekly), **same turn:** prefer **`twinbox_push_confirm_onboarding`** (only `daily`/`weekly` — **no session parameter**, cannot stall on session_target). Alternative: **`twinbox_onboarding_confirm_push`** with optional `session_target` (defaults as in plugin). Do **not** stall to "fetch session info"; call the tool and summarize JSON.
- **Canonical order:** write or obtain file path → **import-material** → (if needed) **onboarding_advance** → **visible summary**. Skipping the middle link is the usual failure mode.

### Onboarding: advancing after the user replies (critical)

Stages such as `profile_setup`, `material_import`, `routing_rules`, and `push_subscription` are **dialogue-first**: you collect answers in chat, but **nothing persists and the stage does not advance** until the Twinbox host runs an **advance** command. **OpenClaw with `plugin-twinbox-task`:** prefer **`twinbox_onboarding_advance`** (wraps `twinbox openclaw onboarding-advance`). **Shell / no plugin:** **`twinbox onboarding next --json`** with the same optional flags is equivalent for advancing state. Do not tell the user they must type a command name — **you** must invoke the tool or CLI once their answer is ready.

#### Near-automatic profile_setup (agent rules — prioritize this)

When **`current_stage` is `profile_setup`** and the user's message contains their substantive answer (role, habits, weekly focus, what to ignore, CC handling, etc.):

1. **Same assistant turn (preferred):** call **`twinbox_onboarding_advance`** with **`profile_notes`** and **`calibration_notes`** — concise summaries of what they said (not a second LLM rewrite pass; you are the summarizer). Use **`cc_downweight`** `on`/`off` only when they clearly stated CC vs primary-inbox preference.
2. **Immediately after the tool returns, same turn:** write a **visible** reply summarizing **`completed_stage`**, **`current_stage`**, and the next **`prompt`** (quote or paraphrase). **Tool-only turns are always a failure** when the assistant omits visible text after tools (empty bubble).
3. **If the platform cannot attach text after tools in one response:** in the **very next** assistant message, call **`twinbox_onboarding_advance`** if not already done, then summarize — **do not** wait for the user to ask for "advance" or "next command."

#### Near-automatic routing_rules (agent rules)

When **`current_stage` is `routing_rules`** and the user message is a **concrete rule request** (e.g. auto-archive/downweight certain emails) or an explicit **skip**:

1. **Preferred (more stable):** build **`rule_json`**, then call **`twinbox_onboarding_finish_routing_rules`** with that string — the plugin runs **`rule add` + `onboarding-advance` in one tool execution**, so the model only needs **one** tool decision (weak hosts often drop the second call when using two separate tools). Use **`skip_rules: true`** if the user clearly skips rules (no `rule_json`).
2. **Fallback:** **`twinbox_rule_add`** then **`twinbox_onboarding_advance`** in the same assistant turn.
3. **Immediately after:** visible text with **`completed_stage`**, **`current_stage`**, next **`prompt`**. **Never** end with tool-only or with "next step" narration and no tools.

**Why it sometimes "worked" and sometimes not:** tool invocation is **probabilistic** per turn; two chained tools double the failure rate. The atomic tool above reduces that to **one** call.

**Recovery if the UI is empty** after the user sent a rule line: **`twinbox_onboarding_finish_routing_rules`** with **`rule_json`** from their message, or shell **`twinbox rule add …`** then **`twinbox openclaw onboarding-advance --json`**.

#### Near-automatic push_subscription

When **`current_stage` is `push_subscription`** and the user confirms (e.g. **confirm / yes / ok**):

1. **Preferred:** **`twinbox_push_confirm_onboarding`** with optional **`daily` / `weekly`** only — schema has **no `session_target`**, so models cannot get stuck "looking up session".
2. **Alternative:** **`twinbox_onboarding_confirm_push`** with optional **`session_target`** (defaults: env, else **`agent:twinbox:main`**).
3. **After the tool returns:** visible summary of subscription + **`completed_stage`** / **`current_stage`**.

**Shell (no plugin):** `twinbox openclaw onboarding-confirm-push agent:twinbox:main --daily on --weekly on --json` (adjust session if you use a non-main target).

**Which session receives pushes:** authoritative `session_target` in `runtime/push-subscriptions.json`. `twinbox_push_confirm_onboarding` resolves **`TWINBOX_PUSH_SESSION_TARGET`** → **`OPENCLAW_SESSION_ID` / `OPENCLAW_SESSION`** → **`agent:twinbox:main`**. To bind the **current chat**, use **`twinbox_onboarding_confirm_push`** with **`session_target`**, or host **`twinbox push subscribe <SESSION> …`**. TTY onboard can pick a custom session. **When Phase 4 refresh runs** is **`daily-refresh` / `weekly-refresh` cron** (defaults in `config/schedules.yaml`, overrides in `runtime/context/schedule-overrides.yaml`); use **`twinbox schedule list` / `twinbox schedule update`**. First daily enable may default to **hourly** refresh; change later if needed.

**Persistence details for profile_setup:** CLI flags **`--profile-notes`** / **`--calibration-notes`** / **`--cc-downweight`** map to `runtime/context/human-context.yaml` (`profile_notes` / `calibration`) plus `twinbox.json.preferences.cc_downweight.enabled`. Phase 2/3 **and Phase 4** **`context-pack.json`** expose these as `human_context.onboarding_profile_notes` / `human_context.calibration_notes`. Legacy `manual-facts.yaml` / `manual-habits.yaml` / `instance-calibration-notes.md` / onboarding `profile_data.*` migrate on first read; afterward the unified file is authoritative. For stages without these flags, use `twinbox context upsert-fact` / `profile-set` if you need durable prose. **`twinbox onboard openclaw`** can capture profile / calibration / pasted reference text in the TTY after LLM validation (multi-line paste, end with a line containing only `.`; body is not echoed back), with optional LLM polish; skip with **`--skip-tty-context-bundle`**. After deploy it continues in the TTY with **routing_rules** and **push_subscription** by default (bridge timer required for push); only in chat: **`--skip-tty-routing-push`**. For **material_import**, show `config/weekly-template.md` first; if the user wants different sections, turn that into Markdown and import with **`twinbox_context_import_material`** (plugin) or `twinbox context import-material FILE --intent template_hint` (or host **`twinbox context import-material --stdin --label STEM --intent …`**), then rerun Phase 4 or wait for weekly refresh — **same turn as the file exists**, do not defer to "next step".

**Recovery if the UI went idle** after the user sent their profile (no assistant text, empty bubble): (1) **`twinbox_onboarding_advance`** with `profile_notes` / `calibration_notes` from the user's **last** message; (2) **`twinbox_onboarding_status`** then **`twinbox_onboarding_advance`** (or `twinbox onboarding status --json` then `twinbox onboarding next --json` with the same profile flags). If the Gateway still drops payloads, run **`twinbox openclaw onboarding-advance --profile-notes '…' --calibration-notes '…' --json`** on the **host shell** and paste stdout into chat.

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

**Data, OpenClaw, env:** `rm -rf ~/.twinbox` (destructive—backup first); remove stale `~/.config/twinbox/*` if present; delete `~/.openclaw/skills/twinbox`, drop `plugin-twinbox-task` per `integrations/openclaw/DEPLOY.md`, then `openclaw gateway restart`. Strip **`TWINBOX_*`**, **`TWINBOX_SETUP_*`**, and mailbox vars from this skill's `metadata.openclaw.requires.env` wherever set (shell, systemd, OpenClaw skill env, CI). New shell: `command -v twinbox` empty.

## Task Entrypoints

**REQUIRED STEPS for any task request:**

1. Match the user's request to a command in the list below.
2. Execute that command now.
3. Write a text answer summarizing the real output.

Reading this file is step 0 only. The turn is **not complete** until you have executed a command (step 2) and written a text answer (step 3). If you have only read files or memory so far, proceed to step 2 immediately — do not end the turn.

| User intent | Command |
|-------------|---------|
| Latest mail / today summary / "what's new in my inbox" | `twinbox task latest-mail --json` (use `--unread-only` if user asks for unread) |
| "What are my todos / pending replies / most important threads" | `twinbox task todo --json` |
| Temporarily ignore a thread / mark as handled but stop reminding | `twinbox queue dismiss THREAD_ID --reason "..." --json`; OpenClaw plugin: `twinbox_queue_dismiss` (`thread_id`, optional `reason`) |
| Mark a thread as completed (must persist; chat checkmarks do not count) | `twinbox queue complete THREAD_ID --action-taken "..." --json`; OpenClaw plugin: `twinbox_queue_complete` (`thread_id`, optional `action_taken`) |
| Restore a dismissed/completed thread | `twinbox queue restore THREAD_ID --json` |
| View current schedule config | `twinbox schedule list --json` or OpenClaw tool `twinbox_schedule_list` |
| Change daily/weekly/nightly schedule time | `twinbox schedule update JOB_NAME --cron "30 9 * * *" --json` or OpenClaw tool `twinbox_schedule_update` |
| Reset a schedule to default time | `twinbox schedule reset JOB_NAME --json` or OpenClaw tool `twinbox_schedule_reset` |
| Enable a background schedule (create OpenClaw cron job) | `twinbox schedule enable JOB_NAME --json` or OpenClaw tool `twinbox_schedule_enable` |
| Disable a background schedule (delete OpenClaw cron job) | `twinbox schedule disable JOB_NAME --json` or OpenClaw tool `twinbox_schedule_disable` |
| "How is X progressing" / progress on a topic | `twinbox task progress QUERY --json` |
| Mailbox status / env diagnosis | `twinbox task mailbox-status --json` |
| Auto-detect email server config | `twinbox mailbox detect EMAIL --json` |
| View current config file | `twinbox config show --json` |
| Configure mailbox credentials (auto-detect or explicit host params, writes `twinbox.json`) | `twinbox mailbox setup --email EMAIL --json` or `twinbox config mailbox-set --email EMAIL --json` (password injected via `TWINBOX_SETUP_IMAP_PASS`) or OpenClaw tool `twinbox_mailbox_setup` |
| Configure LLM API (writes `twinbox.json`) | `twinbox config set-llm --provider openai\|anthropic --model MODEL --api-url URL --json` (key injected via `TWINBOX_SETUP_API_KEY`; must pass model and api-url explicitly, Twinbox no longer ships built-in LLM defaults) or OpenClaw tool `twinbox_config_set_llm`; to match OpenClaw default model: `twinbox config import-llm-from-openclaw --json` (requires inline `apiKey` in `openclaw.json`) or plugin `twinbox_config_import_llm_from_openclaw` |
| Configure Twinbox preferences (including CC downweight) | `twinbox config set-preferences --cc-downweight on\|off --json` |
| Import meeting notes / project ledger / external material into weekly brief | With plugin: prefer **`twinbox_context_import_material`** (`source_path` + `intent`); otherwise `twinbox context import-material FILE --intent reference` (then run `twinbox-orchestrate run --phase 4` or wait for scheduled refresh) |
| Customize weekly template (heading / section order / wording) | Show `config/weekly-template.md` first, then import the user-confirmed new template via **`twinbox_context_import_material`** (`intent=template_hint`) or `twinbox context import-material FILE --intent template_hint` |
| Configure Twinbox integration defaults | `twinbox config integration-set --use-fragment yes\|no [--fragment-path PATH] --json` |
| Configure OpenClaw defaults | `twinbox config openclaw-set [--home PATH] [--bin NAME] [--strict\|--no-strict] [--sync-env\|--no-sync-env] [--restart-gateway\|--no-restart-gateway] --json` |
| OpenClaw setup wizard (single public wizard entry; **after Apply setup completes by default**: OpenClaw merge + plugin/tools observability + **vendor-safe bridge user timer install + health dry-run**; `phase2_ready=true` for Phase 2 handoff; escape hatch `--skip-bridge`; after successful deploy defaults to **daemon start**, `--no-start-daemon` to skip) | `twinbox onboard openclaw [--skip-bridge] [--no-start-daemon] --json` |
| OpenClaw host wiring advanced entry (shares prerequisite bundle with onboard; installs bridge by default; after success defaults to **daemon start**, `--no-start-daemon` to skip) | `twinbox deploy openclaw --json` (`--dry-run`; `--no-restart`; `--no-env-sync`; `--strict`; `--skip-bridge`; `--twinbox-bin`; `--no-start-daemon`; optional `--fragment` / `--no-fragment`) |
| Rollback host wiring (keeps `~/.twinbox`; **also removes bridge user units**) | `twinbox deploy openclaw --rollback --json` (optional `--remove-config`) |
| Vendor-safe OpenClaw bridge (systemd user units only call installed `twinbox`, no dependency on repo `scripts/`) | `twinbox host bridge install\|remove\|status\|poll [--dry-run] [--openclaw-bin …]` |
| OpenClaw Phase 2 onboarding and context material (corresponding CLI: `twinbox openclaw …` / `twinbox context …`) | Plugins: `twinbox_context_import_material` / `twinbox_onboarding_start` / `twinbox_onboarding_status` / `twinbox_onboarding_advance` / **`twinbox_onboarding_finish_routing_rules`** (preferred at routing_rules stage) / **`twinbox_push_confirm_onboarding`** (preferred at push_subscription confirmation, daily/weekly only) / `twinbox_onboarding_confirm_push` |
| Weekly brief lookup | `twinbox task weekly --json` |
| Manage semantic routing rules / "stop sending me this kind of email" | `twinbox rule list --json` / `twinbox rule add --rule-json ...` |
| Test a routing rule against recent threads | `twinbox rule test --rule-id RULE_ID --json` |
| Start onboarding flow | `twinbox onboarding start --json` (human-readable output continues with "Phase 2 of 2") |
| Check onboarding progress | `twinbox onboarding status --json` (human-readable output continues with "Phase 2 of 2") |
| Advance onboarding to next stage | `twinbox onboarding next --json` (human-readable output continues with "Phase 2 of 2") |
| User has answered the current stage in natural language (profile / material / rules / push etc.) | With plugin: **same turn** call **`twinbox_onboarding_advance`** (at profile_setup must include `profile_notes` / `calibration_notes` key points); without plugin: **`twinbox onboarding next --json`** (same flags, add `--cc-downweight off` if user explicitly said CC is their main workflow). Then **must** summarize the returned JSON: `completed_stage`, `current_stage`, next `prompt` (tool-only with no text is never acceptable) |
| Background JSON-RPC daemon (saves Python cold-start; optional) | `daemon start` / triggered by `onboard`/`deploy`. `twinbox daemon status --json` (includes `cache_stats` etc.). Socket: `$TWINBOX_STATE_ROOT/run/daemon.sock`. Go: delivery default can be `twinbox` (**dial failure** silently runs `daemon start` once then retries RPC; `TWINBOX_NO_LAZY_DAEMON=1` disables); still fails → `exec` Python; vendor validates `MANIFEST.json`. `twinbox install --archive …` extracts to `vendor/` and writes `code-root` (dev can use `TWINBOX_CODE_ROOT` override) |
| Multi-mailbox profiles (shared vendor, independent state) | `twinbox --profile NAME …` (`TWINBOX_STATE_ROOT=~/.twinbox/profiles/NAME/state`, `TWINBOX_HOME=~/.twinbox`) |
| Phase loading (Python entry) | `twinbox loading phase1` … `phase4` (orchestration uses `python -m twinbox_core.*`; no `scripts/phase*.sh`; phase1/4 still use himalaya CLI for transport) |
| Sync `twinbox_core` to vendor (host PYTHONPATH) | `twinbox vendor install`; `twinbox vendor status --json` (`integrity_ok` / `file_count`). After install: `PYTHONPATH="$TWINBOX_HOME/vendor"` or `…/state/vendor` (often the same without profiles) + `python3 -m twinbox_core.task_cli …` |
| Subscribe to push (**daily / weekly toggleable independently**; first daily-on attempts hourly `daily-refresh` if no existing override) | `twinbox push subscribe SESSION_ID [--daily on\|off] [--weekly on\|off] --json` |
| Adjust existing subscription cadence | `twinbox push configure SESSION_TARGET --daily on\|off --weekly on\|off --json` |
| List push subscriptions | `twinbox push list --json` |
| Inspect one exact thread / "show me this thread" / "read this thread first" | `twinbox thread inspect THREAD_ID --json` or OpenClaw tool `twinbox_thread_inspect` with `thread_id` |
| Explain why a thread is urgent / pending | `twinbox thread explain THREAD_ID --json` |
| Daily digest | `twinbox digest daily --json` (human-readable mode is Markdown; prefer `--json` for stable consumption) |
| Weekly brief | `twinbox digest weekly --json` (human-readable mode is Markdown, rendered per default `config/weekly-template.md` or latest `template_hint` heading/section order; if `runtime/validation/phase-4/daily-ledger/` snapshots exist, threads that left the action surface earlier this week are backfilled to `important_changes`; not daily auto-accumulation; prefer `--json` for stable consumption) |
| Suggest next actions | `twinbox action suggest --json` |
| Materialize one suggested action | `twinbox action materialize ACTION_ID --json` |
| Review items | `twinbox review list --json` / `twinbox review show REVIEW_ID --json` |
| Refresh hourly/daytime projection (mail data sync) | OpenClaw plugin: **`twinbox_daytime_sync`** (default `daytime-sync`); CLI: `twinbox-orchestrate schedule --job daytime-sync --format json` |
| Refresh full nightly/weekly pipeline | OpenClaw plugin: **`twinbox_daytime_sync`** (`job='nightly-full'`); CLI: `twinbox-orchestrate schedule --job nightly-full --format json` |
| **Full uninstall** | See **Full uninstall** section above (rollback → remove pip/binaries → delete `~/.twinbox` → skill/plugin → clean env) |

## Task Routing Rules

- When the user confirms a thread is **done** or **dismissed**, you must persist queue state: run `twinbox queue complete` / `queue dismiss` with `--json`, or call OpenClaw tools `twinbox_queue_complete` / `twinbox_queue_dismiss`. Resolve `thread_id` from `task todo`, `task latest-mail`, or `thread inspect` — freeform weekly-brief lines alone are not thread keys.
- The file `runtime/context/user-queue-state.yaml` is **created on the first successful** `queue complete` or `queue dismiss`; absence before that is normal.
- Run the command first (`--json`), then summarize stdout in plain text for the user
- Prefer `twinbox task ...` for common user prompts; these are thin wrappers, not a second pipeline
- For the latest mail situation (including casual variants), use `twinbox task latest-mail --json` first; do not start with `preflight` unless connectivity is the explicit problem. If the user explicitly asks for unread, pass `--unread-only` to the command or `unread_only: true` to the tool. **OpenClaw plugin `twinbox_latest_mail`:** if `activity-pulse.json` is missing, the plugin runs `daytime-sync` once and retries inside the same tool call — do not narrate "let me run" in a loop; wait for the tool output.
- If the user wants one exact thread's content/details/status, prefer `twinbox thread inspect THREAD_ID --json` or `twinbox_thread_inspect`; do not use `task progress` unless the request is fuzzy/topic-based.
- If `activity-pulse.json` is missing or stale (tool output will include `recovery_tool: "twinbox_daytime_sync"`), **immediately call `twinbox_daytime_sync`** (plugin) or `twinbox-orchestrate schedule --job daytime-sync` (CLI), then re-call the original task tool and summarize
- `daytime-sync` now enters through the incremental Phase 1 entrypoint (`python -m twinbox_core.incremental_sync`) before Phase 3/4 daytime projection
- The incremental Phase 1 path uses UID watermarks and automatically falls back to the existing full loader when `UIDVALIDITY` changes
- Default schedule definitions now live in `config/schedules.yaml`; `twinbox schedule update/reset` writes `runtime/context/schedule-overrides.yaml` and then attempts to sync the matching Twinbox OpenClaw cron job via `openclaw cron list/edit/add`
- If Gateway access fails, the command still preserves the runtime override and exposes `platform_sync.status=error` in JSON output
- For schedule prompts, prefer native OpenClaw tools `twinbox_schedule_list` / `twinbox_schedule_update` / `twinbox_schedule_reset` / `twinbox_schedule_enable` / `twinbox_schedule_disable` over generic `cron` or workspace search
- For onboarding mailbox setup, prefer native OpenClaw tool `twinbox_mailbox_setup` (passes password via env, never CLI args)
- For onboarding LLM API config, prefer native OpenClaw tool `twinbox_config_set_llm` (passes api_key via env)
- For onboarding after mailbox/LLM, prefer `twinbox_onboarding_start` / `twinbox_onboarding_status` / `twinbox_onboarding_advance`; **push_subscription** prefer **`twinbox_push_confirm_onboarding`** (no session field); otherwise `twinbox_onboarding_confirm_push`, avoiding reliance on `onboarding next` placeholder text
- After the user answers **profile_setup** in natural language, **do not** end the turn without **`twinbox_onboarding_advance`** (or equivalent `onboarding next` / `openclaw onboarding-advance`) **and** a visible summary — the user should not need to name the CLI
- After **writing or staging a file** for Twinbox (e.g. `exec` to `/tmp/...`), **do not** end the turn without **`twinbox_context_import_material`** (or `twinbox context import-material …`) **and** a visible summary — never stop at "Now importing…"
- Prefer **`twinbox_context_import_material`** over generic shell for the same path so the model sees a **named tool** and is less likely to drop the chain
- Stay read-only unless the user explicitly asks for draft/action generation
- **Never end a task turn with only file reads and no text answer.** A turn with `assistant.content=[]` or no text is a failure — always produce real command output followed by a summary

## Hosted Defaults

- Prefer a dedicated `twinbox` agent/session for Twinbox work; keep `main` for general chat
- After skill or env changes, use a fresh Twinbox session; `skillsSnapshot` can freeze old injection results
- Hosted env should come from `skills.entries.twinbox.env`; `state root/twinbox.json` is the Twinbox config source, and any legacy `.env` is only a migration fallback
- If `plugin-twinbox-task` is enabled, prefer an absolute `twinboxBin` pointing to `scripts/twinbox`; if unset, keep `cwd` accurate so the plugin can auto-detect `<cwd>/scripts/twinbox` instead of relying on Gateway PATH
- Treat OpenClaw schedule execution as a Twinbox-managed bridge cron concern; current default definitions come from `config/schedules.yaml`, not skill metadata
- Bridge poller default path: `systemd user timer` → `twinbox host bridge poll` → `openclaw gateway call cron.*` → `twinbox-orchestrate schedule --job …` (vendor install does not depend on `scripts/twinbox_openclaw_bridge_poll.sh`)

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
- `twinbox queue dismiss THREAD_ID --reason "handled" --json`
- `twinbox queue complete THREAD_ID --action-taken "archived" --json`
- `twinbox queue restore THREAD_ID --json`
- `twinbox schedule list --json`
- `twinbox schedule update daily-refresh --cron "30 9 * * *" --json`
- `twinbox schedule reset daily-refresh --json`
- `twinbox task progress QUERY --json`
- `twinbox digest pulse --json` (human-readable mode is Markdown; prefer `--json` for stable consumption)
- `twinbox-orchestrate roots`
- `twinbox daemon status --json` (`status=stopped` is normal when daemon is not enabled)
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
