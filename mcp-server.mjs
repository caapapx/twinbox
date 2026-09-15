#!/usr/bin/env node
/**
 * Twinbox MCP stdio server.
 *
 * Exposes twinbox_* MCP tools wrapping by wrapping
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

async function withAutoSync(cliArgs, label) {
  const r1 = await runCli(cliArgs);
  // A stale pulse is still useful. Do not turn a read request into a blocking
  // IMAP sync; cron or an explicit twinbox_sync owns freshness recovery.
  if (!needsSync(r1.stdout)) return makeResult(r1);

  const rSync = await runCli(["sync", "--json"]);
  if (isError(rSync)) {
    return {
      content: [
        {
          type: "text",
          text: `=== auto sync failed (${label}) ===\n${formatResult(rSync).content[0].text}`,
        },
      ],
      isError: true,
    };
  }
  const r2 = await runCli(cliArgs);
  return {
    content: [
      {
        type: "text",
        text: [
          `=== auto sync (${label}) ===`,
          formatResult(rSync).content[0].text,
          `=== ${cliArgs[0]} (after sync) ===`,
          formatResult(r2).content[0].text,
        ].join("\n\n"),
      },
    ],
    isError: isError(r2),
  };
}

const TOOLS = [
  {
    name: "twinbox_sync",
    description:
      "Fetch mail and run LLM analysis (daytime-sync or nightly-full). " +
      "ONLY call when the user explicitly asks to refresh/re-analyze urgent, pending, or priority results. " +
      "NEVER call for latest-mail requests; call twinbox_latest_mail instead. Chinese: 同步邮件、重新分析待办/紧急度.",
    inputSchema: {
      type: "object",
      properties: {
        job: {
          type: "string",
          enum: ["daytime-sync", "nightly-full", "quick-refresh"],
          default: "daytime-sync",
          description:
            "daytime-sync (fetch + analysis), nightly-full (complete rebuild), quick-refresh (fetch + pulse only, no LLM analysis)",
        },
      },
    },
  },
  {
    name: "twinbox_latest_mail",
    description:
      "Use this ONE tool for requests such as 最新一封邮件, 看下最新邮件, or 有无新邮件. " +
      "Missing pulse triggers a full sync; a merely stale pulse is returned as-is with staleness.stale=true (no IMAP, no LLM). " +
      "Do NOT call twinbox_sync, twinbox_extract, or twinbox_thread_inspect before or after it unless the user explicitly requests re-analysis, a named thread, history, or full body. " +
      "Return only the newest thread's sender, subject, time, and a brief summary.",
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
        from_hour: {
          type: "number",
          description: "Local-hour start filter (inclusive, Asia/Shanghai)",
        },
        to_hour: {
          type: "number",
          description: "Local-hour end filter (exclusive)",
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
  {
    name: "twinbox_onboard",
    description: "Write a user Semantic Pack from ≤5 questionnaire answers. Chinese: 初始化关注点.",
    inputSchema: {
      type: "object",
      properties: {
        approvals: { type: "string" },
        watch: { type: "string" },
        extra: { type: "string" },
        broadcast: { type: "string" },
        sensitive: { type: "string" },
      },
    },
  },
  {
    name: "twinbox_action_proposals",
    description: "Dry-run policy proposals (no SMTP). Chinese: 动作提案.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "twinbox_action_review",
    description: "Confirm or reject a local dry-run proposal. Does not write the mailbox.",
    inputSchema: {
      type: "object",
      properties: {
        proposal_id: { type: "string" },
        action: { type: "string", enum: ["confirm", "reject", "expire"] },
        reason: { type: "string" },
      },
      required: ["proposal_id", "action"],
    },
  },
  {
    name: "twinbox_accounts",
    description:
      "List/add/remove mailbox accounts. Credentials stay in local vault; outputs only password_set booleans. Chinese: 邮箱账号管理.",
    inputSchema: {
      type: "object",
      properties: {
        action: {
          type: "string",
          enum: ["list", "get", "add", "remove"],
          default: "list",
        },
        account_id: { type: "string" },
        email: { type: "string" },
        type: { type: "string", enum: ["personal", "shared", "robot"] },
        host: { type: "string" },
        port: { type: "number" },
        login: { type: "string" },
        password: { type: "string", description: "Write-only; never returned" },
        encryption: { type: "string", enum: ["tls", "starttls", "plain"] },
        default: { type: "boolean" },
      },
    },
  },
  {
    name: "twinbox_ingest",
    description:
      "Reference-only ingest envelopes (no full bodies). Chinese: 引用式邮件摄取.",
    inputSchema: {
      type: "object",
      properties: {
        account_id: { type: "string" },
        since: { type: "string", description: "Opaque cursor from prior ingest" },
        limit: { type: "number" },
      },
    },
  },
  {
    name: "twinbox_events",
    description:
      "Structured event records derived from local analysis (references only). Chinese: 事件抽取.",
    inputSchema: {
      type: "object",
      properties: {
        account_id: { type: "string" },
        limit: { type: "number" },
      },
    },
  },

];

function pushAccountId(cliArgs, args) {
  if (args?.account_id) cliArgs.push("--account-id", String(args.account_id));
  return cliArgs;
}

async function handleToolCall(request) {
  const { name, arguments: args = {} } = request.params;

  switch (name) {
    case "twinbox_sync": {
      const job = args?.job ?? "daytime-sync";
      const cliArgs = pushAccountId(["sync", "--job", job, "--json"], args);
      const r = await runCli(cliArgs);
      return makeResult(r);
    }

    case "twinbox_latest_mail": {
      const cliArgs = pushAccountId(["latest-mail", "--json"], args);
      if (args?.unread_only) cliArgs.push("--unread-only");
      return withAutoSync(cliArgs, "missing pulse");
    }

    case "twinbox_todo": {
      return withAutoSync(pushAccountId(["todo", "--json"], args), "missing pulse");
    }

    case "twinbox_weekly": {
      return withAutoSync(pushAccountId(["weekly", "--json"], args), "missing weekly");
    }

    case "twinbox_thread_inspect": {
      const query = args?.query ?? "";
      const cliArgs = pushAccountId(["thread", query, "--json"], args);
      const r = await runCli(cliArgs);
      return makeResult(r);
    }

    case "twinbox_queue_action": {
      const cliArgs = pushAccountId(["queue", args.action, args.thread_key, "--json"], args);
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
      if (args?.from_hour !== undefined) cliArgs.push("--from-hour", String(args.from_hour));
      if (args?.to_hour !== undefined) cliArgs.push("--to-hour", String(args.to_hour));
      pushAccountId(cliArgs, args);
      const r = await runCli(cliArgs);
      return makeResult(r);
    }

    case "twinbox_status": {
      const r = await runCli(pushAccountId(["status", "--json"], args));
      return makeResult(r);
    }

    case "twinbox_setup": {
      const r = await runCli(["setup", "--json"]);
      return makeResult(r);
    }

    case "twinbox_onboard": {
      const cliArgs = ["onboard", "--json"];
      for (const key of ["approvals", "watch", "extra", "broadcast", "sensitive"]) {
        if (args?.[key]) cliArgs.push(`--${key}`, String(args[key]));
      }
      const r = await runCli(cliArgs);
      return makeResult(r);
    }

    case "twinbox_action_proposals": {
      const r = await runCli(["actions", "--json"]);
      return makeResult(r);
    }

    case "twinbox_action_review": {
      const cliArgs = [
        "actions",
        "review",
        args.proposal_id,
        args.action,
        "--json",
      ];
      if (args.reason) cliArgs.push("--reason", args.reason);
      const r = await runCli(cliArgs);
      return makeResult(r);
    }

    case "twinbox_accounts": {
      const action = args?.action ?? "list";
      const cliArgs = ["accounts", action, "--json"];
      if (args?.account_id) cliArgs.push("--account-id", String(args.account_id));
      if (action === "add") {
        for (const [flag, key] of [
          ["--email", "email"],
          ["--type", "type"],
          ["--host", "host"],
          ["--port", "port"],
          ["--login", "login"],
          ["--password", "password"],
          ["--encryption", "encryption"],
        ]) {
          if (args?.[key] !== undefined && args?.[key] !== null && args?.[key] !== "") {
            cliArgs.push(flag, String(args[key]));
          }
        }
        if (args?.default) cliArgs.push("--default", "true");
      }
      const r = await runCli(cliArgs);
      return makeResult(r);
    }

    case "twinbox_ingest": {
      const cliArgs = pushAccountId(["ingest", "--json"], args);
      if (args?.since) cliArgs.push("--since", String(args.since));
      if (args?.limit !== undefined) cliArgs.push("--limit", String(args.limit));
      const r = await runCli(cliArgs);
      return makeResult(r);
    }

    case "twinbox_events": {
      const cliArgs = pushAccountId(["events", "--json"], args);
      if (args?.limit !== undefined) cliArgs.push("--limit", String(args.limit));
      const r = await runCli(cliArgs);
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
  { name: "twinbox", version: "0.3.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: TOOLS,
}));

server.setRequestHandler(CallToolRequestSchema, handleToolCall);

const transport = new StdioServerTransport();
await server.connect(transport);
