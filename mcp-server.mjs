#!/usr/bin/env node
/**
 * Twinbox MCP stdio server.
 *
 * Exposes the same 9 tools as the OpenClaw plugin by wrapping
 * `python3 -m twinbox_core.cli <cmd> --json`.
 *
 * No Go binary, no daemon, no himalaya.
 */
import { spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

function resolvePython() {
  const env = (process.env.TWINBOX_PYTHON || "").trim();
  if (env) return env;
  return process.platform === "win32" ? "python" : "python3";
}

function resolvePythonPath() {
  const cwd = process.env.TWINBOX_CODE_ROOT || "";
  if (cwd) {
    if (existsSync(join(cwd, "twinbox_core", "__init__.py"))) return cwd;
    if (existsSync(join(cwd, "src", "twinbox_core", "__init__.py")))
      return join(cwd, "src");
  }
  try {
    const root = readFileSync(join(homedir(), ".twinbox", "code-root"), "utf8").trim();
    if (root && existsSync(join(root, "twinbox_core", "__init__.py"))) return root;
  } catch {}
  return "";
}

const PYTHON_PATH = resolvePythonPath();

function runCli(args) {
  return new Promise((resolve, reject) => {
    const env = { ...process.env };
    if (PYTHON_PATH) env.PYTHONPATH = PYTHON_PATH;
    const child = spawn(resolvePython(), ["-m", "twinbox_core.cli", ...args], {
      env,
      shell: false,
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

function formatResult({ code, stdout, stderr }) {
  const text =
    stdout.trim() ||
    (stderr.trim() ? `exit=${code}\n${stderr.trim()}` : `exit=${code} (no output)`);
  return { content: [{ type: "text", text }] };
}

function isError({ code, stdout }) {
  if (code !== 0) return true;
  try {
    const parsed = JSON.parse(stdout.trim());
    return parsed?.ok === false;
  } catch {
    return false;
  }
}

function makeResult(procResult) {
  return { ...formatResult(procResult), isError: isError(procResult) };
}

/** If latest-mail says pulse is missing, auto-sync then retry. */
function needsSync(stdout) {
  try {
    const parsed = JSON.parse(stdout.trim());
    return parsed?.ok === false && parsed?.recovery_tool === "twinbox_sync";
  } catch {
    return false;
  }
}

async function latestMailWithAutoSync(cliArgs) {
  const r1 = await runCli(cliArgs);
  if (!needsSync(r1.stdout)) return makeResult(r1);
  const rSync = await runCli(["sync", "--json"]);
  const r2 = await runCli(cliArgs);
  const parts = [
    "=== auto sync (activity-pulse was missing) ===",
    formatResult(rSync).content[0].text,
    "=== latest-mail (after sync) ===",
    formatResult(r2).content[0].text,
  ];
  return {
    content: [{ type: "text", text: parts.join("\n\n") }],
    isError: isError(r2),
  };
}

const TOOLS = [
  {
    name: "twinbox_sync",
    description:
      "Fetch mail and run LLM analysis (daytime-sync or nightly-full). " +
      "Call this when data is stale or missing. Chinese: 同步邮件、刷新数据.",
    inputSchema: {
      type: "object",
      properties: {
        job: {
          type: "string",
          enum: ["daytime-sync", "nightly-full"],
          default: "daytime-sync",
          description: "daytime-sync (fast) or nightly-full (complete rebuild)",
        },
      },
    },
  },
  {
    name: "twinbox_latest_mail",
    description:
      "Latest mail / activity-pulse snapshot. Auto-syncs if data is missing. " +
      "Chinese: 最新邮件、帮我看下最新的邮件. After return, MUST write a visible summary.",
    inputSchema: {
      type: "object",
      properties: {
        unread_only: {
          type: "boolean",
          description: "If true, only returns threads with unread emails.",
        },
      },
    },
  },
  {
    name: "twinbox_todo",
    description: "Urgent / pending queue snapshot (read-only). Chinese: 待办、待回复.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "twinbox_weekly",
    description: "Weekly brief. Chinese: 周报、每周简报.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "twinbox_thread_inspect",
    description:
      "Inspect or search threads by keyword / thread key. " +
      "Chinese: 查看线程、某个事进展如何.",
    inputSchema: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "Subject fragment, thread key, or keyword",
        },
      },
      required: ["query"],
    },
  },
  {
    name: "twinbox_queue_action",
    description:
      "Mark thread as complete or dismiss it. Chinese: 标记完成、忽略线程. " +
      "MUST call when user confirms a thread is done — chat-only marks do not persist.",
    inputSchema: {
      type: "object",
      properties: {
        action: {
          type: "string",
          enum: ["complete", "dismiss", "restore"],
          description: "complete / dismiss / restore",
        },
        thread_key: {
          type: "string",
          description: "Thread key from activity-pulse",
        },
        reason: {
          type: "string",
          description: "Short note (default: 已完成/已处理)",
        },
      },
      required: ["action", "thread_key"],
    },
  },
  {
    name: "twinbox_extract",
    description:
      "Targeted mail extract by date range + keywords (INBOX/Sent). " +
      "Does NOT refresh daily pulse — use for historical weekly reports or custom keyword searches. " +
      "Chinese: 抽取周报、按关键词拉历史邮件、extract weekly reports.",
    inputSchema: {
      type: "object",
      properties: {
        profile: {
          type: "string",
          description: "Preset profile name, e.g. weekly_report (see config/extract-profiles.yaml)",
        },
        since: {
          type: "string",
          description: "Start date YYYY-MM-DD",
        },
        until: {
          type: "string",
          description: "End date YYYY-MM-DD (exclusive)",
        },
        folders: {
          type: "array",
          items: { type: "string" },
          description: "IMAP folders, e.g. [\"Sent\", \"INBOX\"]",
        },
        subject_contains: {
          type: "string",
          description: "Comma-separated subject substrings (OR)",
        },
        subject_regex: {
          type: "array",
          items: { type: "string" },
          description: "Subject regex patterns (OR)",
        },
        body_contains: {
          type: "string",
          description: "Comma-separated body substrings (OR)",
        },
        weekdays: {
          type: "string",
          description: "Comma-separated weekdays: fri,sat,sun. Empty string disables.",
        },
        from_self: {
          type: "boolean",
          description: "If true, only messages from MAIL_ADDRESS",
        },
        bucket: {
          type: "string",
          enum: ["iso_week", "none"],
          description: "Group output by ISO week (iso_week) or flat list (none)",
        },
      },
    },
  },
  {
    name: "twinbox_status",
    description:
      "Mailbox health + setup status (IMAP preflight, LLM validation, artifact check). " +
      "Chinese: 邮箱状态、检查连接.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "twinbox_setup",
    description:
      "Initial setup: validate IMAP from env vars, import LLM from OpenClaw host. " +
      "Call once after deployment. Chinese: 初始化、配置邮箱.",
    inputSchema: { type: "object", properties: {} },
  },
];

async function handleToolCall(request) {
  const { name, arguments: args = {} } = request.params;

  switch (name) {
    case "twinbox_sync": {
      const job = args?.job ?? "daytime-sync";
      const r = await runCli(["sync", "--job", job, "--json"]);
      return makeResult(r);
    }

    case "twinbox_latest_mail": {
      const cliArgs = ["latest-mail", "--json"];
      if (args?.unread_only) cliArgs.push("--unread-only");
      return latestMailWithAutoSync(cliArgs);
    }

    case "twinbox_todo": {
      const r = await runCli(["todo", "--json"]);
      return makeResult(r);
    }

    case "twinbox_weekly": {
      const r = await runCli(["weekly", "--json"]);
      return makeResult(r);
    }

    case "twinbox_thread_inspect": {
      const query = args?.query ?? "";
      const r = await runCli(["thread", query, "--json"]);
      return makeResult(r);
    }

    case "twinbox_queue_action": {
      const cliArgs = ["queue", args.action, args.thread_key, "--json"];
      if (args.reason) cliArgs.push("--reason", args.reason);
      const r = await runCli(cliArgs);
      return makeResult(r);
    }

    case "twinbox_extract": {
      const cliArgs = ["extract", "--json"];
      if (args?.profile) cliArgs.push("--profile", args.profile);
      if (args?.since) cliArgs.push("--since", args.since);
      if (args?.until) cliArgs.push("--until", args.until);
      if (Array.isArray(args?.folders)) {
        for (const f of args.folders) cliArgs.push("--folder", f);
      }
      if (args?.subject_contains)
        cliArgs.push("--subject-contains", args.subject_contains);
      if (Array.isArray(args?.subject_regex)) {
        for (const re of args.subject_regex) cliArgs.push("--subject-regex", re);
      }
      if (args?.body_contains) cliArgs.push("--body-contains", args.body_contains);
      if (args?.weekdays !== undefined) cliArgs.push("--weekdays", args.weekdays);
      if (args?.from_self) cliArgs.push("--from-self");
      if (args?.bucket) cliArgs.push("--bucket", args.bucket);
      const r = await runCli(cliArgs);
      return makeResult(r);
    }

    case "twinbox_status": {
      const r = await runCli(["status", "--json"]);
      return makeResult(r);
    }

    case "twinbox_setup": {
      const r = await runCli(["setup", "--json"]);
      return makeResult(r);
    }

    default:
      return {
        content: [{ type: "text", text: `Unknown tool: ${name}` }],
        isError: true,
      };
  }
}

const server = new Server(
  { name: "twinbox", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: TOOLS,
}));

server.setRequestHandler(CallToolRequestSchema, handleToolCall);

const transport = new StdioServerTransport();
await server.connect(transport);
