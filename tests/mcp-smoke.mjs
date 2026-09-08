#!/usr/bin/env node
/**
 * Practical smoke test for the twinbox MCP stdio server.
 *
 * Verifies:
 *   1. The server starts over stdio.
 *   2. It responds to MCP initialize.
 *   3. It lists the original 9 tools (additive tools allowed).
 *
 * No IMAP credentials are required because this test does not invoke tools.
 */
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const repoRoot = join(__dirname, "..");
const serverPath = join(repoRoot, "mcp-server.mjs");

const REQUIRED_TOOLS = [
  "twinbox_sync",
  "twinbox_latest_mail",
  "twinbox_todo",
  "twinbox_weekly",
  "twinbox_thread_inspect",
  "twinbox_queue_action",
  "twinbox_extract",
  "twinbox_status",
  "twinbox_setup",
];

function send(stdin, msg) {
  stdin.write(JSON.stringify(msg) + "\n");
}

function readResponse(child, predicate) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("Timed out waiting for MCP response"));
    }, 10000);

    function cleanup() {
      clearTimeout(timer);
      child.stdout.off("data", onData);
      child.stderr.off("data", onErr);
    }

    function onData(chunk) {
      buffer += chunk.toString();
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const msg = JSON.parse(line);
          if (predicate(msg)) {
            cleanup();
            resolve(msg);
            return;
          }
        } catch (err) {
          cleanup();
          reject(new Error(`Invalid JSON from server: ${line}\n${err.message}`));
          return;
        }
      }
    }

    function onErr(chunk) {
      const text = chunk.toString().trim();
      if (text) console.error("[server stderr]", text);
    }

    child.stdout.on("data", onData);
    child.stderr.on("data", onErr);
  });
}

async function main() {
  const child = spawn("node", [serverPath], {
    cwd: repoRoot,
    env: { ...process.env, TWINBOX_CODE_ROOT: repoRoot },
    stdio: ["pipe", "pipe", "pipe"],
  });

  try {
    send(child.stdin, {
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2024-11-05",
        capabilities: {},
        clientInfo: { name: "twinbox-smoke-test", version: "0.1.0" },
      },
    });

    const init = await readResponse(child, (msg) => msg.id === 1);
    if (init.error) {
      throw new Error(`Initialize failed: ${JSON.stringify(init.error)}`);
    }
    console.log("✓ initialize responded");

    send(child.stdin, {
      jsonrpc: "2.0",
      id: 2,
      method: "tools/list",
    });

    const listed = await readResponse(child, (msg) => msg.id === 2);
    if (listed.error) {
      throw new Error(`tools/list failed: ${JSON.stringify(listed.error)}`);
    }

    const tools = listed.result?.tools || [];
    const names = tools.map((t) => t.name).sort();
    const expected = [...REQUIRED_TOOLS].sort();

    console.log(`✓ tools/list returned ${tools.length} tools`);

    const missing = expected.filter((n) => !names.includes(n));

    if (missing.length) {
      throw new Error(`Missing tools: ${missing.join(", ")}`);
    }

    console.log("✓ required 9 tools present (extras allowed)");
    console.log("  " + names.join(", "));
    console.log("\nSmoke test passed.");
  } finally {
    child.kill();
  }
}

main().catch((err) => {
  console.error("\nSmoke test failed:", err.message);
  process.exit(1);
});
