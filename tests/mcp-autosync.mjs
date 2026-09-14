#!/usr/bin/env node
/** Verify stale pulse does not cause MCP auto-sync; missing pulse still does. */
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const serverPath = join(repoRoot, "mcp-server.mjs");

function client(stateRoot) {
  const child = spawn("node", [serverPath], {
    cwd: repoRoot,
    env: { ...process.env, TWINBOX_CODE_ROOT: repoRoot, TWINBOX_STATE_ROOT: stateRoot },
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
      if (resolve) { pending.delete(message.id); resolve(message); }
    }
  });
  let id = 0;
  const call = (method, params) => new Promise((resolve, reject) => {
    const requestId = ++id;
    const timer = setTimeout(() => reject(new Error(`timed out: ${method}`)), 10_000);
    pending.set(requestId, (msg) => { clearTimeout(timer); resolve(msg); });
    child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id: requestId, method, params })}\n`);
  });
  return { child, call };
}

async function invoke(stateRoot) {
  const c = client(stateRoot);
  try {
    await c.call("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "autosync-test", version: "1" } });
    const response = await c.call("tools/call", { name: "twinbox_latest_mail", arguments: {} });
    return response.result.content[0].text;
  } finally {
    c.child.kill();
  }
}

const root = await mkdtemp(join(tmpdir(), "twinbox-mcp-"));
try {
  const pulse = join(root, "runtime", "validation", "phase-4", "activity-pulse.json");
  await (await import("node:fs/promises")).mkdir(dirname(pulse), { recursive: true });
  await writeFile(pulse, JSON.stringify({ generated_at: "2000-01-01T00:00:00+08:00", summary: {} }));
  const stale = await invoke(root);
  if (!stale.includes('"stale": true') || stale.includes("auto sync")) throw new Error(`stale pulse unexpectedly synced: ${stale}`);
  await rm(pulse);
  const missing = await invoke(root);
  if (!missing.includes("auto sync failed")) throw new Error(`missing pulse did not attempt recovery: ${missing}`);
  console.log("✓ stale pulse returned without sync; missing pulse attempted recovery");
} finally {
  await rm(root, { recursive: true, force: true });
}
