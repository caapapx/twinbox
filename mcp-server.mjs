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

// The MCP boundary is platform-visible.  CLI contracts should already avoid
// source bodies, but a defensive serializer keeps a future CLI regression from
// becoming a cross-platform disclosure.  Keep this list to raw-content shapes;
// structured summaries, evidence references, and ordinary error codes remain
// usable by clients.
const PRIVATE_CONTENT_FIELDS = new Set([
  "attachment",
  "attachments",
  "body",
  "body_text",
  "bodytext",
  "content",
  "email_body",
  "emailbody",
  "full_text",
  "fulltext",
  "html",
  "message",
  "mime",
  "mime_body",
  "original_text",
  "originaltext",
  "raw",
  "raw_body",
  "rawbody",
  "rendered_body",
  "source_text",
  "sourcetext",
  "text",
]);
const MAX_PLATFORM_RESPONSE_BYTES = 64 * 1024;
const SAFE_ERROR_CODE = /^[a-z0-9][a-z0-9_.:-]{0,159}$/i;

function normalizedFieldName(key) {
  return String(key).trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

function sanitizePlatformPayload(value, state) {
  if (Array.isArray(value)) return value.map((item) => sanitizePlatformPayload(item, state));
  if (!value || typeof value !== "object") return value;

  const safe = {};
  for (const [key, child] of Object.entries(value)) {
    const normalized = normalizedFieldName(key);
    if (PRIVATE_CONTENT_FIELDS.has(normalized)) {
      state.redactedFields += 1;
      continue;
    }
    // Python exception messages are not an API contract and can include the
    // provider input.  Let only stable error/recovery codes cross this boundary.
    if (normalized === "error" && (typeof child !== "string" || !SAFE_ERROR_CODE.test(child))) {
      state.redactedFields += 1;
      safe[key] = "cli_error";
      continue;
    }
    safe[key] = sanitizePlatformPayload(child, state);
  }
  return safe;
}

function safeCliText({ code, stdout }) {
  const raw = stdout.trim();
  if (!raw) {
    return {
      text: JSON.stringify({ ok: false, error: "cli_no_structured_output", exit_code: code }, null, 2),
      safetyFailure: true,
    };
  }

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    // stderr and non-JSON stdout may include a source fragment from a failed
    // provider; never relay them through the platform boundary.
    return {
      text: JSON.stringify({ ok: false, error: "cli_unstructured_output", exit_code: code }, null, 2),
      safetyFailure: true,
    };
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return {
      text: JSON.stringify({ ok: false, error: "cli_invalid_envelope", exit_code: code }, null, 2),
      safetyFailure: true,
    };
  }

  const state = { redactedFields: 0 };
  let safe = sanitizePlatformPayload(payload, state);
  let safetyFailure = state.redactedFields > 0;
  if (safetyFailure) {
    safe = {
      ...safe,
      ok: false,
      error: "platform_output_redacted",
      redacted_field_count: state.redactedFields,
    };
  }

  let text = JSON.stringify(safe, null, 2);
  if (Buffer.byteLength(text, "utf8") > MAX_PLATFORM_RESPONSE_BYTES) {
    text = JSON.stringify(
      { ok: false, error: "platform_response_too_large", max_bytes: MAX_PLATFORM_RESPONSE_BYTES },
      null,
      2,
    );
    safetyFailure = true;
  }
  return { text, safetyFailure };
}

function formatResult(procResult) {
  const safe = safeCliText(procResult);
  return { content: [{ type: "text", text: safe.text }], safetyFailure: safe.safetyFailure };
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
  const formatted = formatResult(procResult);
  return {
    content: formatted.content,
    isError: isError(procResult) || formatted.safetyFailure,
  };
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

function flagValue(args, flag) {
  const i = args.indexOf(flag);
  if (i >= 0 && i + 1 < args.length) return String(args[i + 1] || "");
  return "";
}

function isDegraded(procResult) {
  try {
    const parsed = JSON.parse(procResult.stdout.trim());
    return Array.isArray(parsed?.degraded) && parsed.degraded.length > 0;
  } catch {
    return false;
  }
}

/** Missing weekly needs a full-window rewrite; latest/todo keep default daytime-sync. */
function recoverySyncArgs(cliArgs) {
  const syncArgs = cliArgs[0] === "weekly"
    ? ["sync", "--job", "nightly-full", "--json"]
    : ["sync", "--json"];
  const accountId = flagValue(cliArgs, "--account-id");
  if (accountId) syncArgs.push("--account-id", accountId);
  return syncArgs;
}

function recoveryFailed(procResult, cliArgs) {
  if (isError(procResult)) return true;
  return cliArgs[0] === "weekly" && isDegraded(procResult);
}

async function withAutoSync(cliArgs, label) {
  const r1 = await runCli(cliArgs);
  // A stale pulse is still useful. Do not turn a read request into a blocking
  // IMAP sync; cron or an explicit twinbox_sync owns freshness recovery.
  if (!needsSync(r1.stdout)) return makeResult(r1);

  const rSync = await runCli(recoverySyncArgs(cliArgs));
  const syncFormatted = formatResult(rSync);
  if (recoveryFailed(rSync, cliArgs) || syncFormatted.safetyFailure) {
    return {
      content: [
        {
          type: "text",
          text: `=== auto sync failed (${label}) ===\n${syncFormatted.content[0].text}`,
        },
      ],
      isError: true,
    };
  }
  const r2 = await runCli(cliArgs);
  const resultFormatted = formatResult(r2);
  const stillMissing = needsSync(r2.stdout);
  return {
    content: [
      {
        type: "text",
        text: [
          `=== auto sync (${label}) ===`,
          syncFormatted.content[0].text,
          stillMissing
            ? `=== ${cliArgs[0]} still missing after recovery ===`
            : `=== ${cliArgs[0]} (after sync) ===`,
          resultFormatted.content[0].text,
        ].join("\n\n"),
      },
    ],
    isError: stillMissing || isError(r2) || resultFormatted.safetyFailure,
  };
}

const ACCOUNT_ID_PROP = {
  type: "string",
  description:
    "Mailbox account_id. Omit to use twinbox.json default_account_id.",
};

const SYNC_ACCOUNT_ID_PROP = {
  type: "string",
  description:
    "If set, sync only this account. Omit to sync all registered accounts.",
};

const TOOLS = [
  {
    name: "twinbox_sync",
    description:
      "Fetch mail and run LLM analysis (daytime-sync or nightly-full). " +
      "ONLY call when the user explicitly asks to refresh/re-analyze urgent, pending, or priority results. " +
      "NEVER call for latest-mail requests; call twinbox_latest_mail instead. Chinese: 同步邮件、重新分析待办/紧急度.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        job: {
          type: "string",
          enum: ["daytime-sync", "nightly-full", "quick-refresh"],
          default: "daytime-sync",
          description:
            "daytime-sync (fetch + analysis), nightly-full (complete rebuild), quick-refresh (fetch + pulse only, no LLM analysis)",
        },
        account_id: SYNC_ACCOUNT_ID_PROP,
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
      additionalProperties: false,
      properties: {
        unread_only: {
          type: "boolean",
          description: "If true, only returns threads with unread emails.",
        },
        account_id: ACCOUNT_ID_PROP,
      },
    },
  },
  {
    name: "twinbox_todo",
    description: "Urgent / pending queue snapshot (read-only). Chinese: 待办、待回复.",
    inputSchema: { type: "object", additionalProperties: false, properties: { account_id: ACCOUNT_ID_PROP } },
  },
  {
    name: "twinbox_weekly",
    description: "Weekly brief. Chinese: 周报、每周简报.",
    inputSchema: { type: "object", additionalProperties: false, properties: { account_id: ACCOUNT_ID_PROP } },
  },
  {
    name: "twinbox_thread_inspect",
    description:
      "Inspect or search threads by keyword / thread key. " +
      "Chinese: 查看线程、某个事进展如何.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        query: {
          type: "string",
          description: "Subject fragment, thread key, or keyword",
        },
        account_id: ACCOUNT_ID_PROP,
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
      additionalProperties: false,
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
        account_id: ACCOUNT_ID_PROP,
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
      additionalProperties: false,
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
        source: {
          type: "string",
          enum: ["auto", "local", "imap"],
          description:
            "Where to read mail: auto uses local retention when the range is covered, else IMAP; " +
            "local never calls IMAP; imap always hits the mailbox. Default auto.",
        },
        account_id: ACCOUNT_ID_PROP,
      },
    },
  },
  {
    name: "twinbox_status",
    description:
      "Mailbox health + setup status (IMAP preflight, LLM validation, artifact check). " +
      "Chinese: 邮箱状态、检查连接.",
    inputSchema: { type: "object", additionalProperties: false, properties: { account_id: ACCOUNT_ID_PROP } },
  },
  {
    name: "twinbox_setup",
    description:
      "Initial setup: validate IMAP from env vars, import LLM from OpenClaw host. " +
      "Call once after deployment. Chinese: 初始化、配置邮箱.",
    inputSchema: { type: "object", additionalProperties: false, properties: {} },
  },
  {
    name: "twinbox_onboard",
    description: "Write a user Semantic Pack from ≤5 questionnaire answers. Chinese: 初始化关注点.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
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
    inputSchema: { type: "object", additionalProperties: false, properties: {} },
  },
  {
    name: "twinbox_action_review",
    description:
      "Review a local dry-run proposal. Confirm requires a short-lived, single-use confirmation_token from a prior human-confirmation turn; after a proposal issues a token, stop the agent turn and wait for the human. Never writes the mailbox.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        proposal_id: { type: "string" },
        action: { type: "string", enum: ["confirm", "reject", "expire"] },
        confirmation_token: {
          type: "string",
          description: "Required only for confirm; issued by twinbox_action_proposals and must come from a later human-confirmation turn.",
        },
        reason: { type: "string" },
      },
      required: ["proposal_id", "action"],
    },
  },
  {
    name: "twinbox_accounts",
    description:
      "List/add/remove/set-default mailbox accounts. Credentials stay in local vault; outputs only password_set booleans. Chinese: 邮箱账号管理.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        action: {
          type: "string",
          enum: ["list", "get", "add", "remove", "set-default"],
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
      additionalProperties: false,
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
      additionalProperties: false,
      properties: {
        account_id: { type: "string" },
        limit: { type: "number" },
      },
    },
  },
  {
    name: "twinbox_semantics",
    description:
      "Dynamic semantic catalog and case projections; evidence refs are opt-in. Chinese: 分类目录、事项分类与证据展开.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        account_id: { type: "string" },
        action: { type: "string", enum: ["catalog", "list", "get"] },
        case_ref: { type: "string" },
        include_evidence: { type: "boolean" },
      },
    },
  },
  {
    name: "twinbox_feedback",
    description:
      "Submit an authorized v1 correction proposal, human confirmation, or execution receipt. Never changes mailbox state.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        account_id: { type: "string" },
        payload: { type: "object", description: "feedback.schema.json v1 payload" },
      },
      required: ["payload"],
    },
  },
  {
    name: "twinbox_case_ledger",
    description:
      "Read-only current view of the append-only case lifecycle ledger: " +
      "for each case_ref + attribute, the line with the latest valid_from, skipping needs_confirmation lines. " +
      "Chinese: 案例生命周期账本当前视图.",
    inputSchema: { type: "object", additionalProperties: false, properties: { account_id: ACCOUNT_ID_PROP } },
  },

];

function undeclaredToolArguments(name, args) {
  const tool = TOOLS.find((item) => item.name === name);
  if (!tool) return `Unknown tool: ${name}`;
  const allowed = new Set(Object.keys(tool.inputSchema?.properties || {}));
  const extra = Object.keys(args || {}).filter((key) => !allowed.has(key));
  if (!extra.length) return "";
  return `undeclared_argument:${extra.sort().join(",")}`;
}

function pushAccountId(cliArgs, args) {
  if (args?.account_id) cliArgs.push("--account-id", String(args.account_id));
  return cliArgs;
}

async function handleToolCall(request) {
  const { name, arguments: args = {} } = request.params;
  const undeclared = undeclaredToolArguments(name, args);
  if (undeclared) {
    return {
      content: [{ type: "text", text: undeclared }],
      isError: true,
    };
  }

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
      if (args?.source) cliArgs.push("--source", String(args.source));
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
      if (args.confirmation_token) cliArgs.push("--confirmation-token", String(args.confirmation_token));
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

    case "twinbox_case_ledger": {
      const r = await runCli(pushAccountId(["case-ledger", "--json"], args));
      return makeResult(r);
    }

    case "twinbox_semantics": {
      const action = args?.action ?? "list";
      const cliArgs = pushAccountId(["semantics", action, "--json"], args);
      if (args?.case_ref) cliArgs.push("--case-ref", String(args.case_ref));
      if (args?.include_evidence) cliArgs.push("--include-evidence");
      const r = await runCli(cliArgs);
      return makeResult(r);
    }

    case "twinbox_feedback": {
      const cliArgs = pushAccountId(["feedback", "--json"], args);
      cliArgs.push("--payload-json", JSON.stringify(args.payload));
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
