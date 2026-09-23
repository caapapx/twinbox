#!/usr/bin/env node
/**
 * T028: every MCP-visible TwinBox tool must fail closed rather than relay raw
 * mail-shaped fields returned by the CLI.  A local stub deliberately returns
 * the same sentinel under common full-content field names for every command;
 * the assertion is made on the stdio protocol boundary, not an internal
 * helper, so newly registered tools are covered automatically.
 */
import { chmod, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const serverPath = join(repoRoot, "mcp-server.mjs");
const LEAK_SENTINEL = "TWINBOX_FULL_MESSAGE_MUST_NOT_REACH_PLATFORM_9e71c4";

const REQUIRED_ARGUMENTS = {
  twinbox_thread_inspect: { query: "safe-probe" },
  twinbox_queue_action: { action: "complete", thread_key: "safe-probe" },
  twinbox_action_review: { proposal_id: "safe-probe", action: "reject" },
  twinbox_feedback: { payload: { kind: "correction_proposal", actor_ref: "safe-probe" } },
};

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function startClient(python, extraEnv = {}) {
  const child = spawn("node", [serverPath], {
    cwd: repoRoot,
    env: {
      ...process.env,
      TWINBOX_CODE_ROOT: repoRoot,
      TWINBOX_PYTHON: python,
      TWINBOX_OUTPUT_SAFETY_SENTINEL: LEAK_SENTINEL,
      ...extraEnv,
    },
    stdio: ["pipe", "pipe", "pipe"],
  });
  let buffer = "";
  const pending = new Map();
  child.stdout.on("data", (chunk) => {
    buffer += chunk;
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      const message = JSON.parse(line);
      const resolve = pending.get(message.id);
      if (resolve) {
        pending.delete(message.id);
        resolve(message);
      }
    }
  });
  let id = 0;
  const call = (method, params) => new Promise((resolve, reject) => {
    const requestId = ++id;
    const timer = setTimeout(() => {
      pending.delete(requestId);
      reject(new Error(`timed out: ${method}`));
    }, 10_000);
    pending.set(requestId, (message) => {
      clearTimeout(timer);
      resolve(message);
    });
    child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id: requestId, method, params })}\n`);
  });
  return { child, call };
}

const root = await mkdtemp(join(tmpdir(), "twinbox-mcp-output-safety-"));
const python = join(root, "unsafe-cli.py");
const stub = `#!/usr/bin/env python3
import json, os, sys
sentinel = os.environ["TWINBOX_OUTPUT_SAFETY_SENTINEL"]
if os.environ.get("TWINBOX_FORCE_UNSTRUCTURED_OUTPUT") == "1":
    print(sentinel)
    raise SystemExit(0)
# This intentionally models a future CLI regression: a raw source message is
# accidentally nested under several common field names while the command says ok.
payload = {
  "ok": True,
  "safe": "diagnostic-only",
  "body": sentinel,
  "body_text": sentinel,
  "html": sentinel,
  "raw": sentinel,
  "message": sentinel,
  "error": sentinel,
  "nested": {"content": sentinel, "source_text": sentinel},
  "items": [{"text": sentinel, "raw_body": sentinel}],
}
print(json.dumps(payload, ensure_ascii=False))
`;

await writeFile(python, stub, { mode: 0o700 });
await chmod(python, 0o700);
const client = startClient(python);
try {
  const initialized = await client.call("initialize", {
    protocolVersion: "2024-11-05",
    capabilities: {},
    clientInfo: { name: "mcp-output-safety", version: "1" },
  });
  assert(!initialized.error, `initialize failed: ${JSON.stringify(initialized.error)}`);

  const listed = await client.call("tools/list", {});
  const tools = listed.result?.tools || [];
  assert(tools.length > 0, "tools/list returned no MCP-visible tools");

  for (const tool of tools) {
    const response = await client.call("tools/call", {
      name: tool.name,
      arguments: REQUIRED_ARGUMENTS[tool.name] || {},
    });
    assert(!response.error, `${tool.name}: tools/call protocol error: ${JSON.stringify(response.error)}`);
    const result = response.result || {};
    const platformText = JSON.stringify(result);
    assert(
      !platformText.includes(LEAK_SENTINEL),
      `${tool.name}: raw-content sentinel leaked through MCP response`,
    );
    assert(
      result.isError === true,
      `${tool.name}: redacted tool response must be marked isError rather than trusted as complete`,
    );
    assert(
      platformText.includes("platform_output_redacted"),
      `${tool.name}: redaction must be explicit to the platform consumer`,
    );
  }
  const rawClient = startClient(python, { TWINBOX_FORCE_UNSTRUCTURED_OUTPUT: "1" });
  try {
    const rawInit = await rawClient.call("initialize", {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: { name: "mcp-output-safety-unstructured", version: "1" },
    });
    assert(!rawInit.error, `unstructured client initialize failed: ${JSON.stringify(rawInit.error)}`);
    const rawResponse = await rawClient.call("tools/call", { name: "twinbox_status", arguments: {} });
    const rawText = JSON.stringify(rawResponse.result || {});
    assert(!rawText.includes(LEAK_SENTINEL), "unstructured CLI stdout leaked through MCP response");
    assert(rawResponse.result?.isError === true, "unstructured CLI stdout must be marked isError");
    assert(rawText.includes("cli_unstructured_output"), `unstructured output lacked stable failure code: ${rawText}`);
  } finally {
    rawClient.child.kill();
  }
  console.log(`✓ ${tools.length} MCP-visible tools reject raw mail-shaped CLI fields and unstructured stdout`);
} finally {
  client.child.kill();
  await rm(root, { recursive: true, force: true });
}
