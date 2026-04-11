/**
 * Twinbox Lite — 8 OpenClaw tools for email intelligence.
 *
 * Each tool calls `python3 -m twinbox_core.cli <cmd> --json` directly.
 * No Go binary, no daemon, no himalaya.
 */
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { Type } from "@sinclair/typebox";

function resolvePython() {
  const env = (process.env.TWINBOX_PYTHON || "").trim();
  if (env) return env;
  return process.platform === "win32" ? "python" : "python3";
}

function resolvePythonPath(pluginConfig) {
  // Check for code-root pointer or cwd
  const cwd = pluginConfig?.cwd || process.env.TWINBOX_CODE_ROOT || "";
  if (cwd) {
    if (existsSync(join(cwd, "twinbox_core", "__init__.py"))) return cwd;
    if (existsSync(join(cwd, "src", "twinbox_core", "__init__.py"))) return join(cwd, "src");
  }
  // Fallback: read ~/.twinbox/code-root
  try {
    const root = readFileSync(join(homedir(), ".twinbox", "code-root"), "utf8").trim();
    if (root && existsSync(join(root, "twinbox_core", "__init__.py"))) return root;
  } catch {}
  return "";
}

function runCli(args, pythonPath) {
  return new Promise((resolve, reject) => {
    const env = { ...process.env };
    if (pythonPath) env.PYTHONPATH = pythonPath;
    const child = spawn(resolvePython(), ["-m", "twinbox_core.cli", ...args], {
      env,
      shell: false,
    });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (d) => { stdout += d.toString(); });
    child.stderr?.on("data", (d) => { stderr += d.toString(); });
    child.on("error", reject);
    child.on("close", (code) => {
      resolve({ code: code ?? 1, stdout, stderr });
    });
  });
}

function formatResult({ code, stdout, stderr }) {
  const text = stdout.trim() ||
    (stderr.trim() ? `exit=${code}\n${stderr.trim()}` : `exit=${code} (no output)`);
  return { content: [{ type: "text", text }] };
}

/** If latest-mail says pulse is missing, auto-sync then retry. */
function needsSync(stdout) {
  try {
    const parsed = JSON.parse(stdout.trim());
    return parsed?.ok === false && parsed?.recovery_tool === "twinbox_sync";
  } catch { return false; }
}

async function latestMailWithAutoSync(cliArgs, pythonPath) {
  const r1 = await runCli(cliArgs, pythonPath);
  if (!needsSync(r1.stdout)) return formatResult(r1);
  // Auto-sync
  const rSync = await runCli(["sync", "--json"], pythonPath);
  const r2 = await runCli(cliArgs, pythonPath);
  const parts = [
    "=== auto sync (activity-pulse was missing) ===",
    formatResult(rSync).content[0].text,
    "=== latest-mail (after sync) ===",
    formatResult(r2).content[0].text,
  ];
  return { content: [{ type: "text", text: parts.join("\n\n") }] };
}

/** @param {{ pluginConfig?: object, registerTool: (t: object) => void }} api */
export function registerTwinboxTools(api) {
  const pythonPath = resolvePythonPath(api.pluginConfig);

  // 1. twinbox_sync
  api.registerTool({
    name: "twinbox_sync",
    description:
      "Fetch mail and run LLM analysis (daytime-sync or nightly-full). " +
      "Call this when data is stale or missing. Chinese: 同步邮件、刷新数据.",
    parameters: Type.Object({
      job: Type.Optional(
        Type.Union([Type.Literal("daytime-sync"), Type.Literal("nightly-full")], {
          default: "daytime-sync",
          description: "daytime-sync (fast) or nightly-full (complete rebuild)",
        })
      ),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const job = params?.job ?? "daytime-sync";
      const r = await runCli(["sync", "--job", job, "--json"], pythonPath);
      return formatResult(r);
    },
  });

  // 2. twinbox_latest_mail
  api.registerTool({
    name: "twinbox_latest_mail",
    description:
      "Latest mail / activity-pulse snapshot. Auto-syncs if data is missing. " +
      "Chinese: 最新邮件、帮我看下最新的邮件. After return, MUST write a visible summary.",
    parameters: Type.Object({
      unread_only: Type.Optional(
        Type.Boolean({ description: "If true, only returns threads with unread emails." })
      ),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const cliArgs = ["latest-mail", "--json"];
      if (params?.unread_only) cliArgs.push("--unread-only");
      return latestMailWithAutoSync(cliArgs, pythonPath);
    },
  });

  // 3. twinbox_todo
  api.registerTool({
    name: "twinbox_todo",
    description:
      "Urgent / pending queue snapshot (read-only). Chinese: 待办、待回复.",
    parameters: Type.Object({}),
    async execute() {
      const r = await runCli(["todo", "--json"], pythonPath);
      return formatResult(r);
    },
  });

  // 4. twinbox_weekly
  api.registerTool({
    name: "twinbox_weekly",
    description: "Weekly brief. Chinese: 周报、每周简报.",
    parameters: Type.Object({}),
    async execute() {
      const r = await runCli(["weekly", "--json"], pythonPath);
      return formatResult(r);
    },
  });

  // 5. twinbox_thread_inspect
  api.registerTool({
    name: "twinbox_thread_inspect",
    description:
      "Inspect or search threads by keyword / thread key. " +
      "Chinese: 查看线程、某个事进展如何.",
    parameters: Type.Object({
      query: Type.String({ description: "Subject fragment, thread key, or keyword" }),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const r = await runCli(["thread", params?.query ?? "", "--json"], pythonPath);
      return formatResult(r);
    },
  });

  // 6. twinbox_queue_action
  api.registerTool({
    name: "twinbox_queue_action",
    description:
      "Mark thread as complete or dismiss it. Chinese: 标记完成、忽略线程. " +
      "MUST call when user confirms a thread is done — chat-only marks do not persist.",
    parameters: Type.Object({
      action: Type.Union([
        Type.Literal("complete"),
        Type.Literal("dismiss"),
        Type.Literal("restore"),
      ], { description: "complete / dismiss / restore" }),
      thread_key: Type.String({ description: "Thread key from activity-pulse" }),
      reason: Type.Optional(Type.String({ description: "Short note (default: 已完成/已处理)" })),
    }),
    async execute(...args) {
      const params = args.length >= 2 ? args[1] : args[0];
      const cliArgs = ["queue", params.action, params.thread_key, "--json"];
      if (params.reason) cliArgs.push("--reason", params.reason);
      const r = await runCli(cliArgs, pythonPath);
      return formatResult(r);
    },
  });

  // 7. twinbox_status
  api.registerTool({
    name: "twinbox_status",
    description:
      "Mailbox health + setup status (IMAP preflight, LLM validation, artifact check). " +
      "Chinese: 邮箱状态、检查连接.",
    parameters: Type.Object({}),
    async execute() {
      const r = await runCli(["status", "--json"], pythonPath);
      return formatResult(r);
    },
  });

  // 8. twinbox_setup
  api.registerTool({
    name: "twinbox_setup",
    description:
      "Initial setup: validate IMAP from env vars, import LLM from OpenClaw host. " +
      "Call once after deployment. Chinese: 初始化、配置邮箱.",
    parameters: Type.Object({}),
    async execute() {
      const r = await runCli(["setup", "--json"], pythonPath);
      return formatResult(r);
    },
  });
}
