/**
 * Registers Twinbox `task … --json` tools on an OpenClaw plugin `api` object.
 * Kept free of `openclaw` imports so `node --test` can run with only @sinclair/typebox.
 */
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { Type } from "@sinclair/typebox";

export function toolOpts(pluginConfig) {
  const twinboxBin =
    (typeof pluginConfig?.twinboxBin === "string" && pluginConfig.twinboxBin) || "twinbox";

  let cwd = pluginConfig?.cwd || process.env.TWINBOX_CODE_ROOT;

  // Fallback: read ~/.config/twinbox/code-root (same logic as twinbox script)
  if (!cwd) {
    try {
      const codeRootFile = `${homedir()}/.config/twinbox/code-root`;
      cwd = readFileSync(codeRootFile, "utf8").trim();
    } catch {
      // File doesn't exist or unreadable, leave cwd undefined
    }
  }

  return { twinboxBin, cwd };
}

export function runTwinbox(args, { twinboxBin, cwd }) {
  return new Promise((resolve, reject) => {
    const child = spawn(twinboxBin, args, {
      cwd,
      shell: false,
      env: { ...process.env },
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

/** @param {{ pluginConfig?: object, registerTool: (t: object) => void }} api */
export function registerTwinboxTaskTools(api) {
  const opts = toolOpts(api.pluginConfig);

  api.registerTool({
    name: "twinbox_latest_mail",
    description:
      "Latest mail / activity-pulse snapshot (read-only). Chinese triggers: 最新邮件、最新邮件情况、帮我查看下最新的邮件情况. Unread triggers (MUST set unread_only=true): 未读、最新未读、只看未读、未读邮件. Runs: twinbox task latest-mail [--unread-only] --json. After this tool returns, you MUST reply with a visible text summary (never end with empty assistant text).",
    parameters: Type.Object({
      unread_only: Type.Optional(Type.Boolean({ description: "If true, only returns threads that contain unread emails." })),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const cliArgs = ["task", "latest-mail", "--json"];
      if (params?.unread_only) {
        cliArgs.push("--unread-only");
      }
      const r = await runTwinbox(cliArgs, opts);
      return formatResult(r);
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
    description: "Add or update a semantic routing rule. The rule_json should be a valid JSON string matching the RoutingRule schema.",
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
}
