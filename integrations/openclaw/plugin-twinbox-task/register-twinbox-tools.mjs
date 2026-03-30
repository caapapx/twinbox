/**
 * Registers Twinbox `task … --json` tools on an OpenClaw plugin `api` object.
 * Kept free of `openclaw` imports so `node --test` can run with only @sinclair/typebox.
 */
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { Type } from "@sinclair/typebox";

export function toolOpts(pluginConfig) {
  const configuredTwinboxBin =
    typeof pluginConfig?.twinboxBin === "string" && pluginConfig.twinboxBin.trim()
      ? pluginConfig.twinboxBin.trim()
      : null;

  let cwd = pluginConfig?.cwd || process.env.TWINBOX_CODE_ROOT;

  // Fallback: read ~/.twinbox/code-root, then legacy ~/.config/twinbox/code-root
  if (!cwd) {
    const candidates = [
      `${homedir()}/.twinbox/code-root`,
      `${homedir()}/.config/twinbox/code-root`,
    ];
    for (const codeRootFile of candidates) {
      try {
        cwd = readFileSync(codeRootFile, "utf8").trim();
        if (cwd) break;
      } catch {
        /* try next */
      }
    }
  }

  const twinboxBin =
    configuredTwinboxBin ||
    (cwd && existsSync(join(cwd, "scripts", "twinbox"))
      ? join(cwd, "scripts", "twinbox")
      : "twinbox");

  const openclawBin =
    typeof pluginConfig?.openclawBin === "string" && pluginConfig.openclawBin.trim()
      ? pluginConfig.openclawBin.trim()
      : process.env.OPENCLAW_BIN || "openclaw";

  const orchestrateInvoke = resolveOrchestrateInvoke(pluginConfig, cwd);

  return { twinboxBin, cwd, openclawBin, orchestrateInvoke };
}

/** Prefer `python3` on Unix; `python` on Windows when TWINBOX_PYTHON is unset. */
export function defaultPythonCommand() {
  const raw =
    typeof process.env.TWINBOX_PYTHON === "string" ? process.env.TWINBOX_PYTHON.trim() : "";
  if (raw) return raw;
  return process.platform === "win32" ? "python" : "python3";
}

/**
 * @param {string | undefined} cwd TWINBOX_CODE_ROOT (git repo or vendor extract)
 * @returns {{ command: string, argsPrefix: string[], env: Record<string, string> }}
 */
export function resolveOrchestrateInvoke(pluginConfig, cwd) {
  const configured =
    typeof pluginConfig?.orchestrateBin === "string" && pluginConfig.orchestrateBin.trim()
      ? pluginConfig.orchestrateBin.trim()
      : typeof process.env.TWINBOX_ORCHESTRATE_BIN === "string" &&
          process.env.TWINBOX_ORCHESTRATE_BIN.trim()
        ? process.env.TWINBOX_ORCHESTRATE_BIN.trim()
        : null;
  if (configured) {
    return { command: configured, argsPrefix: [], env: {} };
  }
  if (cwd && existsSync(join(cwd, "scripts", "twinbox_orchestrate.sh"))) {
    return { command: join(cwd, "scripts", "twinbox_orchestrate.sh"), argsPrefix: [], env: {} };
  }
  const pyPath = orchestratePythonPath(cwd);
  if (pyPath) {
    return {
      command: defaultPythonCommand(),
      argsPrefix: ["-m", "twinbox_core.orchestration"],
      env: { PYTHONPATH: pyPath },
    };
  }
  return { command: "twinbox-orchestrate", argsPrefix: [], env: {} };
}

/**
 * Git repo: src/twinbox_core. Vendor tarball: twinbox_core/ at code root.
 * @returns {string | null} PYTHONPATH segment (single root containing the package)
 */
export function orchestratePythonPath(cwd) {
  if (!cwd) return null;
  const srcPkg = join(cwd, "src", "twinbox_core");
  const flatPkg = join(cwd, "twinbox_core");
  if (existsSync(srcPkg)) return join(cwd, "src");
  if (existsSync(flatPkg)) return cwd;
  return null;
}

function appendOpenclawBin(cliArgs, openclawBin) {
  if (openclawBin && openclawBin !== "openclaw") {
    cliArgs.push("--openclaw-bin", openclawBin);
  }
}

export function runTwinbox(args, { twinboxBin, cwd }, extraEnv = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(twinboxBin, args, {
      cwd,
      shell: false,
      env: { ...process.env, ...extraEnv },
    });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (d) => {
      stdout += d.toString();
    });
    child.stderr?.on("data", (d) => {
      stderr += d.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      resolve({ code: code ?? 1, stdout, stderr });
    });
  });
}

export function runOrchestrate(args, { orchestrateInvoke, cwd }, extraEnv = {}) {
  return new Promise((resolve, reject) => {
    const prefix = orchestrateInvoke.argsPrefix || [];
    const fullArgs = [...prefix, ...args];
    const child = spawn(orchestrateInvoke.command, fullArgs, {
      cwd,
      shell: false,
      env: { ...process.env, ...orchestrateInvoke.env, ...extraEnv },
    });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (d) => {
      stdout += d.toString();
    });
    child.stderr?.on("data", (d) => {
      stderr += d.toString();
    });
    child.on("error", reject);
    child.on("close", (code) => {
      resolve({ code: code ?? 1, stdout, stderr });
    });
  });
}

export function formatResult({ code, stdout, stderr }) {
  const text =
    stdout.trim() ||
    (stderr.trim() ? `exit=${code}\n${stderr.trim()}` : `exit=${code} (no output)`);
  return { content: [{ type: "text", text }] };
}

/**
 * When latest-mail JSON says pulse is missing, weak hosts often loop on "让我执行：" without
 * calling twinbox_daytime_sync. Run daytime-sync inside this tool, then retry once.
 */
export function latestMailNeedsDaytimeSync(stdout, stderr, code) {
  const out = (stdout || "").trim();
  try {
    const parsed = JSON.parse(out);
    if (parsed && parsed.ok === false && parsed.recovery_tool === "twinbox_daytime_sync") {
      return true;
    }
  } catch {
    /* not JSON */
  }
  const err = `${stderr || ""}\n${out}`.toLowerCase();
  return (
    code !== 0 &&
    (err.includes("activity-pulse") || err.includes("missing activity-pulse"))
  );
}

export async function runLatestMailCli(cliArgs, opts) {
  const r1 = await runTwinbox(cliArgs, opts);
  if (!latestMailNeedsDaytimeSync(r1.stdout, r1.stderr, r1.code ?? 1)) {
    return formatResult(r1);
  }
  const rSync = await runOrchestrate(["schedule", "--job", "daytime-sync", "--format", "json"], opts);
  const r2 = await runTwinbox(cliArgs, opts);
  const parts = [
    "=== automatic daytime-sync (activity-pulse was missing; weak models must not narrate without this) ===",
    formatResult(rSync).content[0].text,
    "=== twinbox task latest-mail (after sync) ===",
    formatResult(r2).content[0].text,
  ];
  return { content: [{ type: "text", text: parts.join("\n\n") }] };
}

/** Default OpenClaw chat session for twinbox agent main (see integrations/openclaw/README.md). */
const DEFAULT_TWINBOX_PUSH_SESSION = "agent:twinbox:main";

/**
 * @param {{ session_target?: string } | undefined} params
 */
export function resolvePushSessionTarget(params) {
  const explicit = params?.session_target;
  if (explicit != null && String(explicit).trim() !== "") {
    return String(explicit).trim();
  }
  const env =
    process.env.TWINBOX_PUSH_SESSION_TARGET?.trim() ||
    process.env.OPENCLAW_SESSION_ID?.trim() ||
    process.env.OPENCLAW_SESSION?.trim();
  if (env) return env;
  return DEFAULT_TWINBOX_PUSH_SESSION;
}

/** @param {{ pluginConfig?: object, registerTool: (t: object) => void }} api */
export function registerTwinboxTaskTools(api) {
  const opts = toolOpts(api.pluginConfig);

  api.registerTool({
    name: "twinbox_latest_mail",
    description:
      "Latest mail / activity-pulse snapshot. If activity-pulse.json is missing, this tool automatically runs daytime-sync once then retries latest-mail inside the same execution — do NOT say 让我执行, 先同步邮件数据然后查看最新邮件, or loop text; wait for the combined output. Never repeat the same sentence twice in one assistant message; call this tool immediately with at most one short lead-in. Chinese: 最新邮件、帮我看下最新的邮件. Unread (unread_only=true): 未读、只看未读. After return, MUST write a visible summary.",
    parameters: Type.Object({
      unread_only: Type.Optional(Type.Boolean({ description: "If true, only returns threads that contain unread emails." })),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const cliArgs = ["task", "latest-mail", "--json"];
      if (params?.unread_only) {
        cliArgs.push("--unread-only");
      }
      return runLatestMailCli(cliArgs, opts);
    },
  });

  api.registerTool({
    name: "twinbox_todo",
    description: "Todo / urgent queue snapshot (read-only). Runs: twinbox task todo --json",
    parameters: Type.Object({}),
    async execute() {
      const r = await runTwinbox(["task", "todo", "--json"], opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_mailbox_status",
    description: "Mailbox preflight / env diagnosis (read-only). Runs: twinbox task mailbox-status --json",
    parameters: Type.Object({}),
    async execute() {
      const r = await runTwinbox(["task", "mailbox-status", "--json"], opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_thread_progress",
    description:
      "Thread progress by subject / keyword / thread key (read-only). Use this for topic progress or fuzzy lookup, not for returning one exact thread's full state/content. Runs: twinbox task progress QUERY --json",
    parameters: Type.Object({
      query: Type.String({ description: "Subject fragment, thread key, or business keyword" }),
      limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 20, default: 5 })),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const limit = params?.limit ?? 5;
      const q = params?.query ?? "";
      const args2 = ["task", "progress", q, "--limit", String(limit), "--json"];
      const r = await runTwinbox(args2, opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_thread_inspect",
    description:
      "Inspect one exact thread's state/details (read-only). Use this when the user asks to return a specific thread's content, read the thread first, or inspect one known thread key. Runs: twinbox thread inspect THREAD_ID --json",
    parameters: Type.Object({
      thread_id: Type.String({ description: "Exact thread ID / thread key to inspect" }),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const threadId = params?.thread_id ?? "";
      const r = await runTwinbox(["thread", "inspect", threadId, "--json"], opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_queue_complete",
    description:
      "Persist thread as completed: writes runtime/context/user-queue-state.yaml so activity pulse and push no longer surface this thread_key until restored. Chinese: 已完成、标记完成、不用再提醒这个线程. MUST call when the user confirms a thread is done — chat-only checkmarks do not persist. Get thread_id from task todo / latest-mail / thread inspect. Runs: twinbox queue complete THREAD_ID --action-taken ... --json",
    parameters: Type.Object({
      thread_id: Type.String({ description: "Thread key / thread_id from Twinbox artifacts (same as CLI queue complete)" }),
      action_taken: Type.Optional(
        Type.String({ description: "Short note what the user did (default: 已完成)" }),
      ),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const threadId = params?.thread_id ?? "";
      const action = params?.action_taken ?? "已完成";
      const cliArgs = ["queue", "complete", threadId, "--action-taken", action, "--json"];
      const r = await runTwinbox(cliArgs, opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_queue_dismiss",
    description:
      "Temporarily hide a thread from queue views; reappears if the thread fingerprint changes (new mail). Chinese: 先忽略、别再提醒、稍后处理. Persists to user-queue-state.yaml. MUST call for real suppression — not a chat-only acknowledgment. Runs: twinbox queue dismiss THREAD_ID --reason ... --json",
    parameters: Type.Object({
      thread_id: Type.String({ description: "Thread key / thread_id from Twinbox artifacts" }),
      reason: Type.Optional(Type.String({ description: "Why dismissed (default: 已处理)" })),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const threadId = params?.thread_id ?? "";
      const reason = params?.reason ?? "已处理";
      const cliArgs = ["queue", "dismiss", threadId, "--reason", reason, "--json"];
      const r = await runTwinbox(cliArgs, opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_schedule_list",
    description:
      "List effective Twinbox schedules (default + runtime override). Use for prompts like 查看当前调度、每天什么时候刷新、定时任务现在怎么配. Runs: twinbox schedule list --json",
    parameters: Type.Object({}),
    async execute() {
      const r = await runTwinbox(["schedule", "list", "--json"], opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_schedule_update",
    description:
      "Update one Twinbox schedule override and attempt platform-side OpenClaw cron sync. Use for prompts like 每日刷新改成每小时、把 nightly 改到凌晨 3 点. Runs: twinbox schedule update JOB_NAME --cron ... --json",
    parameters: Type.Object({
      job_name: Type.String({ description: "Schedule name: daily-refresh | weekly-refresh | nightly-full-refresh" }),
      cron: Type.String({ description: "Cron expression, usually 5-field; e.g. 0 * * * *" }),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const jobName = params?.job_name ?? "";
      const cron = params?.cron ?? "";
      const cliArgs = ["schedule", "update", jobName, "--cron", cron, "--json"];
      const r = await runTwinbox(cliArgs, opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_schedule_reset",
    description:
      "Reset one Twinbox schedule back to the default cron and attempt platform-side OpenClaw cron sync. Use for prompts like 恢复默认时间、把 daily 改回默认. Runs: twinbox schedule reset JOB_NAME --json",
    parameters: Type.Object({
      job_name: Type.String({ description: "Schedule name: daily-refresh | weekly-refresh | nightly-full-refresh" }),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const jobName = params?.job_name ?? "";
      const cliArgs = ["schedule", "reset", jobName, "--json"];
      const r = await runTwinbox(cliArgs, opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_schedule_enable",
    description:
      "Enable a Twinbox background schedule and create the corresponding OpenClaw cron job. Use for prompts like 启用日间同步、开启夜间全量、打开周报刷新. Runs: twinbox schedule enable JOB_NAME --json",
    parameters: Type.Object({
      job_name: Type.String({ description: "Schedule name: daily-refresh | weekly-refresh | nightly-full-refresh" }),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const jobName = params?.job_name ?? "";
      const r = await runTwinbox(["schedule", "enable", jobName, "--json"], opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_schedule_disable",
    description:
      "Disable a Twinbox background schedule and delete the corresponding OpenClaw cron job. Use for prompts like 关闭日间同步、禁用夜间全量、不要周报刷新. Runs: twinbox schedule disable JOB_NAME --json",
    parameters: Type.Object({
      job_name: Type.String({ description: "Schedule name: daily-refresh | weekly-refresh | nightly-full-refresh" }),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const jobName = params?.job_name ?? "";
      const r = await runTwinbox(["schedule", "disable", jobName, "--json"], opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_weekly",
    description: "Weekly brief task projection (read-only). Runs: twinbox task weekly --json",
    parameters: Type.Object({}),
    async execute() {
      const r = await runTwinbox(["task", "weekly", "--json"], opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_rule_list",
    description: "List all semantic routing rules. Runs: twinbox rule list --json",
    parameters: Type.Object({}),
    async execute() {
      const r = await runTwinbox(["rule", "list", "--json"], opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_rule_add",
    description:
      "Add or update a semantic routing rule (rule_json = full rule object JSON). During onboarding current_stage=routing_rules: when the user states a filter in natural language, call this in the SAME turn you parse it, then twinbox_onboarding_advance — do not stop with empty text. If they say skip/跳过 with no rule, call onboarding_advance only. See repo config/routing-rules.yaml for shape. After tool returns, MUST output visible summary.",
    parameters: Type.Object({
      rule_json: Type.String({ description: "Rule definition in JSON format" }),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const r = await runTwinbox(["rule", "add", "--rule-json", params.rule_json, "--json"], opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_rule_remove",
    description: "Remove a semantic routing rule by ID.",
    parameters: Type.Object({
      rule_id: Type.String({ description: "Rule ID to remove" }),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const r = await runTwinbox(["rule", "remove", params.rule_id, "--json"], opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_rule_test",
    description: "Test a semantic routing rule against recent threads to see its impact before saving. Provide EITHER rule_id (for existing rules) OR rule_json (for new/unsaved rules).",
    parameters: Type.Object({
      rule_id: Type.Optional(Type.String({ description: "Rule ID to test (if it already exists)" })),
      rule_json: Type.Optional(Type.String({ description: "Rule definition in JSON format (to test before adding)" })),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      let cliArgs = ["rule", "test", "--json"];
      if (params.rule_json) {
        cliArgs.push("--rule-json", params.rule_json);
      } else if (params.rule_id) {
        cliArgs.push("--rule-id", params.rule_id);
      } else {
        return { content: [{ type: "text", text: "Error: Must provide either rule_id or rule_json" }] };
      }
      const r = await runTwinbox(cliArgs, opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_mailbox_setup",
    description:
      "Configure mailbox credentials: auto-detect IMAP/SMTP servers from email, write .env, and run preflight. Password is passed via imap_pass param (injected as env var, never exposed in CLI args). Use during onboarding mailbox_login stage. Runs: twinbox mailbox setup --email EMAIL --json",
    parameters: Type.Object({
      email: Type.String({ description: "Email address to configure" }),
      imap_pass: Type.String({ description: "IMAP/app password (injected as TWINBOX_SETUP_IMAP_PASS, not logged)" }),
      smtp_pass: Type.Optional(Type.String({ description: "SMTP password if different from IMAP password (injected as TWINBOX_SETUP_SMTP_PASS)" })),
      imap_login: Type.Optional(Type.String({ description: "Override IMAP login username (default: email)" })),
      smtp_login: Type.Optional(Type.String({ description: "Override SMTP login username (default: email)" })),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const cliArgs = ["mailbox", "setup", "--email", params.email ?? "", "--json"];
      if (params.imap_login) cliArgs.push("--imap-login", params.imap_login);
      if (params.smtp_login) cliArgs.push("--smtp-login", params.smtp_login);
      const extraEnv = { TWINBOX_SETUP_IMAP_PASS: params.imap_pass ?? "" };
      if (params.smtp_pass) extraEnv.TWINBOX_SETUP_SMTP_PASS = params.smtp_pass;
      const r = await runTwinbox(cliArgs, opts, extraEnv);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_config_set_llm",
    description:
      "Configure LLM API backend: writes api_key to .env and validates backend. api_key is injected as TWINBOX_SETUP_API_KEY (not logged). Use during onboarding llm_setup stage. Runs: twinbox config set-llm --provider PROVIDER --json",
    parameters: Type.Object({
      api_key: Type.String({ description: "LLM API key (injected as TWINBOX_SETUP_API_KEY, not logged)" }),
      provider: Type.Optional(Type.Union([Type.Literal("openai"), Type.Literal("anthropic")], { default: "openai", description: "LLM provider: openai (default, also works for OpenAI-compatible endpoints) or anthropic" })),
      model: Type.Optional(Type.String({ description: "Model ID override (e.g. gpt-4o, claude-sonnet-4-6)" })),
      api_url: Type.Optional(Type.String({ description: "API URL override for OpenAI-compatible endpoints" })),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const cliArgs = ["config", "set-llm", "--provider", params.provider ?? "openai", "--json"];
      if (params.model) cliArgs.push("--model", params.model);
      if (params.api_url) cliArgs.push("--api-url", params.api_url);
      const extraEnv = { TWINBOX_SETUP_API_KEY: params.api_key ?? "" };
      const r = await runTwinbox(cliArgs, opts, extraEnv);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_context_import_material",
    description:
      "Import a host file into Twinbox material-extracts (weekly reference or template). Call in the SAME turn you have a real path (e.g. after writing /tmp/...md). Do NOT say you will import in the next message — that pattern often yields empty assistant bubbles on weak tool hosts. reference = 会议纪要/台账/周报素材; template_hint = 自定义周报章节. Runs: twinbox context import-material SOURCE --intent INTENT. After this tool returns, MUST output visible text (stdout summary); then twinbox_onboarding_advance if material_import is done.",
    parameters: Type.Object({
      source_path: Type.String({ description: "Absolute or ~ path to file on the Gateway host" }),
      intent: Type.Optional(
        Type.Union([Type.Literal("reference"), Type.Literal("template_hint")], {
          description: "reference = digest material; template_hint = weekly template structure",
        }),
      ),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const intent = params?.intent ?? "reference";
      const source = params?.source_path ?? "";
      const cliArgs = ["context", "import-material", source, "--intent", intent];
      const r = await runTwinbox(cliArgs, opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_onboarding_start",
    description:
      "Start or resume Twinbox Phase 2 onboarding (JSON). Runs: twinbox openclaw onboarding-start. After this tool returns, you MUST reply with a visible text summary.",
    parameters: Type.Object({}),
    async execute() {
      const cliArgs = ["openclaw", "onboarding-start"];
      const r = await runTwinbox(cliArgs, opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_onboarding_status",
    description:
      "Twinbox onboarding progress and readiness (JSON). Runs: twinbox openclaw onboarding-status. After this tool returns, you MUST reply with a visible text summary.",
    parameters: Type.Object({}),
    async execute() {
      const cliArgs = ["openclaw", "onboarding-status"];
      const r = await runTwinbox(cliArgs, opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_onboarding_advance",
    description:
      "Advance onboarding after the user finished the current stage in chat. profile_setup: SAME turn as their answer — pass profile_notes, calibration_notes; optional cc_downweight. routing_rules: SAME turn after twinbox_rule_add (or alone if user skipped rules). Other stages: call when stage work is done. Runs: twinbox openclaw onboarding-advance. After this tool returns you MUST output visible text: completed_stage, current_stage, next prompt — never tool-only (empty bubble).",
    parameters: Type.Object({
      profile_notes: Type.Optional(Type.String({ description: "Notes for profile_setup stage" })),
      calibration_notes: Type.Optional(Type.String({ description: "Weekly focus / ignore guidance" })),
      cc_downweight: Type.Optional(Type.Union([Type.Literal("on"), Type.Literal("off")])),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const cliArgs = ["openclaw", "onboarding-advance"];
      if (params?.profile_notes) cliArgs.push("--profile-notes", params.profile_notes);
      if (params?.calibration_notes) cliArgs.push("--calibration-notes", params.calibration_notes);
      if (params?.cc_downweight) cliArgs.push("--cc-downweight", params.cc_downweight);
      const r = await runTwinbox(cliArgs, opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_onboarding_finish_routing_rules",
    description:
      "PREFERRED when current_stage is routing_rules: ONE tool call runs `twinbox rule add` (unless skip_rules) then `twinbox openclaw onboarding-advance` inside the plugin — more stable than chaining twinbox_rule_add + twinbox_onboarding_advance (weak hosts often drop the second call). Pass rule_json (full rule object JSON string). If user says skip/跳过 with no rule, pass skip_rules=true. After return, MUST output visible text summarizing the advance JSON.",
    parameters: Type.Object({
      rule_json: Type.Optional(Type.String({ description: "Full rule JSON; required unless skip_rules=true" })),
      skip_rules: Type.Optional(Type.Boolean({ description: "If true, only advance onboarding without adding a rule" })),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const skip = params?.skip_rules === true;
      let r1 = null;
      if (!skip) {
        const rj = params?.rule_json;
        if (!rj || !String(rj).trim()) {
          return {
            content: [{ type: "text", text: "Error: provide rule_json or set skip_rules=true" }],
          };
        }
        r1 = await runTwinbox(["rule", "add", "--rule-json", rj, "--json"], opts);
        if (r1.code !== 0) {
          return formatResult(r1);
        }
      }
      const r2 = await runTwinbox(["openclaw", "onboarding-advance"], opts);
      const parts = [];
      if (!skip && r1) {
        parts.push(`=== rule add ===\n${formatResult(r1).content[0].text}`);
      }
      parts.push(`=== onboarding advance ===\n${formatResult(r2).content[0].text}`);
      return { content: [{ type: "text", text: parts.join("\n\n") }] };
    },
  });

  api.registerTool({
    name: "twinbox_onboarding_confirm_push",
    description:
      "Complete push_subscription: subscribe session, sync schedules, advance onboarding. Runs: twinbox openclaw onboarding-confirm-push SESSION. session_target is OPTIONAL: if omitted or unknown, the plugin uses TWINBOX_PUSH_SESSION_TARGET / OPENCLAW_SESSION_ID / OPENCLAW_SESSION env, else agent:twinbox:main (standard twinbox agent main chat). Do NOT stall to look up session — call this tool when the user says 确认. After this tool returns, you MUST reply with a visible text summary.",
    parameters: Type.Object({
      session_target: Type.Optional(
        Type.String({
          description:
            "OpenClaw session id for push routing; omit to use env or agent:twinbox:main",
        }),
      ),
      daily: Type.Optional(Type.Union([Type.Literal("on"), Type.Literal("off")], { default: "on" })),
      weekly: Type.Optional(Type.Union([Type.Literal("on"), Type.Literal("off")], { default: "on" })),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const session = resolvePushSessionTarget(params);
      const daily = params?.daily ?? "on";
      const weekly = params?.weekly ?? "on";
      const cliArgs = ["openclaw", "onboarding-confirm-push", session, "--daily", daily, "--weekly", weekly];
      appendOpenclawBin(cliArgs, opts.openclawBin);
      const r = await runTwinbox(cliArgs, opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_push_confirm_onboarding",
    description:
      "ZH: 用户在 push_subscription 阶段说「确认」时用本工具；不要传 session、不要先查会话。EN: Same as twinbox_onboarding_confirm_push with default session only (agent:twinbox:main or env). Parameters are ONLY daily/weekly — no session field, so weak models cannot stall asking for session_target. After return, MUST output visible summary.",
    parameters: Type.Object({
      daily: Type.Optional(Type.Union([Type.Literal("on"), Type.Literal("off")], { default: "on" })),
      weekly: Type.Optional(Type.Union([Type.Literal("on"), Type.Literal("off")], { default: "on" })),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const session = resolvePushSessionTarget({});
      const daily = params?.daily ?? "on";
      const weekly = params?.weekly ?? "on";
      const cliArgs = ["openclaw", "onboarding-confirm-push", session, "--daily", daily, "--weekly", weekly];
      appendOpenclawBin(cliArgs, opts.openclawBin);
      const r = await runTwinbox(cliArgs, opts);
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_config_import_llm_from_openclaw",
    description:
      "Copy Twinbox LLM settings from the host OpenClaw openclaw.json default model (agents.defaults.model): reads provider baseUrl + apiKey + model id. No API key param needed. Runs: twinbox config import-llm-from-openclaw --json",
    parameters: Type.Object({
      openclaw_json: Type.Optional(
        Type.String({
          description:
            "Path to openclaw.json (default: ~/.openclaw/openclaw.json on the Gateway host)",
        }),
      ),
      dry_run: Type.Optional(
        Type.Boolean({
          description: "If true, only print what would be applied (no write, no validation)",
        }),
      ),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const cliArgs = ["config", "import-llm-from-openclaw", "--json"];
      if (params.openclaw_json) cliArgs.push("--openclaw-json", params.openclaw_json);
      if (params.dry_run) cliArgs.push("--dry-run");
      const r = await runTwinbox(cliArgs, opts, {});
      return formatResult(r);
    },
  });

  api.registerTool({
    name: "twinbox_daytime_sync",
    description:
      "Refresh Twinbox mail data (activity-pulse, Phase 1→3→4 daytime projection). Call this AUTOMATICALLY when twinbox_latest_mail or twinbox_todo returns 'Missing activity-pulse.json' or stale data. Chinese: 同步邮件、刷新邮件数据、运行同步. Takes ~30-120s. After return, MUST re-call the original task tool and summarize results.",
    parameters: Type.Object({
      job: Type.Optional(
        Type.Union(
          [Type.Literal("daytime-sync"), Type.Literal("nightly-full")],
          { default: "daytime-sync", description: "daytime-sync (fast incremental, default) or nightly-full (complete rebuild)" },
        ),
      ),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const job = params?.job ?? "daytime-sync";
      const r = await runOrchestrate(["schedule", "--job", job, "--format", "json"], opts);
      return formatResult(r);
    },
  });
}
