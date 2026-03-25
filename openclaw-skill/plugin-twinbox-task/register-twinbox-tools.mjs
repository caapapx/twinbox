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
      "Latest mail / daily-urgent style snapshot (read-only). Use for Chinese prompts like 最新邮件、帮我查看下最新的邮件情况. Runs: twinbox task latest-mail --json",
    parameters: Type.Object({}),
    async execute() {
      const r = await runTwinbox(["task", "latest-mail", "--json"], opts);
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
      "Thread progress by subject / keyword / thread key (read-only). Runs: twinbox task progress QUERY --json",
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
    name: "twinbox_weekly",
    description: "Weekly brief task projection (read-only). Runs: twinbox task weekly --json",
    parameters: Type.Object({}),
    async execute() {
      const r = await runTwinbox(["task", "weekly", "--json"], opts);
      return formatResult(r);
    },
  });
}
