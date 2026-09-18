#!/usr/bin/env node
/** FR-006: stale pulse does not auto-sync; missing pulse/weekly recovers with the right job and account. */
import { chmod, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const serverPath = join(repoRoot, "mcp-server.mjs");
const stubPath = join(repoRoot, "tests", "mcp_cli_stub.py");

function client(stateRoot, extraEnv = {}) {
  const child = spawn("node", [serverPath], {
    cwd: repoRoot,
    env: {
      ...process.env,
      TWINBOX_CODE_ROOT: repoRoot,
      TWINBOX_STATE_ROOT: stateRoot,
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
  const call = (method, params) =>
    new Promise((resolve, reject) => {
      const requestId = ++id;
      const timer = setTimeout(() => reject(new Error(`timed out: ${method}`)), 10_000);
      pending.set(requestId, (msg) => {
        clearTimeout(timer);
        resolve(msg);
      });
      child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", id: requestId, method, params })}\n`);
    });
  return { child, call };
}

async function invoke(stateRoot, name, args = {}, extraEnv = {}) {
  const c = client(stateRoot, extraEnv);
  try {
    await c.call("initialize", {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: { name: "autosync-test", version: "1" },
    });
    return await c.call("tools/call", { name, arguments: args });
  } finally {
    c.child.kill();
  }
}

function textOf(response) {
  return response?.result?.content?.[0]?.text || "";
}

function syncArgv(logText) {
  return logText
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line))
    .filter((args) => args[0] === "sync");
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

const root = await mkdtemp(join(tmpdir(), "twinbox-mcp-"));
await chmod(stubPath, 0o755);
try {
  const pulse = join(root, "runtime", "validation", "phase-4", "activity-pulse.json");
  await mkdir(dirname(pulse), { recursive: true });
  await writeFile(pulse, JSON.stringify({ generated_at: "2000-01-01T00:00:00+08:00", summary: {} }));

  const stale = textOf(await invoke(root, "twinbox_latest_mail"));
  assert(stale.includes('"stale": true'), `stale pulse missing staleness: ${stale}`);
  assert(!stale.includes("auto sync"), `stale pulse unexpectedly synced: ${stale}`);

  await rm(pulse);
  const missing = textOf(await invoke(root, "twinbox_latest_mail"));
  assert(missing.includes("auto sync failed"), `missing pulse did not attempt recovery: ${missing}`);

  const accountLog = join(root, "argv-account.jsonl");
  const accountResp = await invoke(
    root,
    "twinbox_latest_mail",
    { account_id: "acct-a" },
    {
      TWINBOX_PYTHON: stubPath,
      TWINBOX_CLI_ARGV_LOG: accountLog,
      TWINBOX_STUB_SYNC: "fail",
    },
  );
  const accountText = textOf(accountResp);
  assert(accountText.includes("auto sync failed"), `account recovery did not fail closed: ${accountText}`);
  const accountSync = syncArgv(await readFile(accountLog, "utf8"));
  assert(accountSync.length === 1, `expected one recovery sync, got ${JSON.stringify(accountSync)}`);
  assert(
    accountSync[0].includes("--account-id") && accountSync[0].includes("acct-a"),
    `recovery sync dropped account_id: ${JSON.stringify(accountSync[0])}`,
  );
  assert(
    !accountSync[0].includes("nightly-full"),
    `latest-mail recovery must not use nightly-full: ${JSON.stringify(accountSync[0])}`,
  );

  const weeklyLog = join(root, "argv-weekly.jsonl");
  const weeklyResp = await invoke(
    root,
    "twinbox_weekly",
    { account_id: "acct-b" },
    {
      TWINBOX_PYTHON: stubPath,
      TWINBOX_CLI_ARGV_LOG: weeklyLog,
      TWINBOX_STUB_SYNC: "fail",
    },
  );
  const weeklyText = textOf(weeklyResp);
  assert(weeklyText.includes("auto sync failed"), `weekly recovery did not fail closed: ${weeklyText}`);
  const weeklySync = syncArgv(await readFile(weeklyLog, "utf8"));
  assert(weeklySync.length === 1, `expected one weekly recovery sync, got ${JSON.stringify(weeklySync)}`);
  const jobAt = weeklySync[0].indexOf("--job");
  assert(
    jobAt >= 0 && weeklySync[0][jobAt + 1] === "nightly-full",
    `weekly recovery must use nightly-full: ${JSON.stringify(weeklySync[0])}`,
  );
  assert(
    weeklySync[0].includes("--account-id") && weeklySync[0].includes("acct-b"),
    `weekly recovery dropped account_id: ${JSON.stringify(weeklySync[0])}`,
  );

  const stillLog = join(root, "argv-still.jsonl");
  const stillResp = await invoke(
    root,
    "twinbox_weekly",
    {},
    {
      TWINBOX_PYTHON: stubPath,
      TWINBOX_CLI_ARGV_LOG: stillLog,
      TWINBOX_STUB_SYNC: "ok",
      TWINBOX_STUB_QUERY: "missing",
    },
  );
  const stillText = textOf(stillResp);
  assert(stillResp.result?.isError === true, `still-missing weekly must be isError: ${JSON.stringify(stillResp.result)}`);
  assert(
    stillText.includes("still missing after recovery"),
    `still-missing weekly lacked recovery banner: ${stillText}`,
  );
  assert(
    stillText.includes("Missing weekly-brief-raw.json"),
    `still-missing weekly dropped CLI error: ${stillText}`,
  );
  assert(!stillText.includes("auto sync failed"), `successful stub sync should not use failed banner: ${stillText}`);

  const degradedResp = await invoke(
    root,
    "twinbox_weekly",
    {},
    {
      TWINBOX_PYTHON: stubPath,
      TWINBOX_CLI_ARGV_LOG: join(root, "argv-degraded.jsonl"),
      TWINBOX_STUB_SYNC: "degraded",
    },
  );
  const degradedText = textOf(degradedResp);
  assert(degradedResp.result?.isError === true, `degraded weekly recovery must be isError`);
  assert(
    degradedText.includes("auto sync failed"),
    `degraded weekly must not look like a complete brief: ${degradedText}`,
  );
  assert(
    !degradedText.includes("(after sync)"),
    `degraded weekly retried as if recovery succeeded: ${degradedText}`,
  );

  console.log(
    "✓ stale zero-sync; missing pulse recovers; account_id and weekly nightly-full propagate; sync/degraded/still-missing fail closed",
  );
} finally {
  await rm(root, { recursive: true, force: true });
}
