import { chmodSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import {
  registerTwinboxTaskTools,
  toolOpts,
  formatResult,
  resolvePushSessionTarget,
  latestMailNeedsDaytimeSync,
  resolveOrchestrateInvoke,
  orchestratePythonPath,
} from "./register-twinbox-tools.mjs";

test("toolOpts uses env TWINBOX_CODE_ROOT when cwd omitted", () => {
  const prev = process.env.TWINBOX_CODE_ROOT;
  process.env.TWINBOX_CODE_ROOT = "/tmp/tb-root";
  try {
    assert.deepEqual(toolOpts({ twinboxBin: "twinbox" }), {
      twinboxBin: "twinbox",
      cwd: "/tmp/tb-root",
      openclawBin: "openclaw",
      orchestrateInvoke: {
        command: "twinbox-orchestrate",
        argsPrefix: [],
        env: {},
      },
    });
  } finally {
    if (prev === undefined) {
      delete process.env.TWINBOX_CODE_ROOT;
    } else {
      process.env.TWINBOX_CODE_ROOT = prev;
    }
  }
});

test("toolOpts prefers cwd/scripts/twinbox when twinboxBin omitted", () => {
  const dir = mkdtempSync(join(tmpdir(), "twinbox-plugin-"));
  const scriptsDir = join(dir, "scripts");
  const twinboxScript = join(scriptsDir, "twinbox");
  mkdirSync(scriptsDir, { recursive: true });
  writeFileSync(twinboxScript, "#!/bin/sh\nexit 0\n");
  chmodSync(twinboxScript, 0o755);

  const orchestrateScript = join(scriptsDir, "twinbox_orchestrate.sh");
  writeFileSync(orchestrateScript, "#!/bin/sh\nexit 0\n");
  chmodSync(orchestrateScript, 0o755);

  assert.deepEqual(toolOpts({ cwd: dir }), {
    twinboxBin: twinboxScript,
    cwd: dir,
    openclawBin: "openclaw",
    orchestrateInvoke: {
      command: orchestrateScript,
      argsPrefix: [],
      env: {},
    },
  });
});

test("toolOpts uses python -m when code root has twinbox_core (vendor) but no orchestrate script", () => {
  const dir = mkdtempSync(join(tmpdir(), "twinbox-vendor-"));
  mkdirSync(join(dir, "twinbox_core"), { recursive: true });
  writeFileSync(join(dir, "twinbox_core", "__init__.py"), "");
  const opts = toolOpts({ cwd: dir });
  assert.equal(opts.orchestrateInvoke.command, process.platform === "win32" ? "python" : "python3");
  assert.deepEqual(opts.orchestrateInvoke.argsPrefix, ["-m", "twinbox_core.orchestration"]);
  assert.equal(opts.orchestrateInvoke.env.PYTHONPATH, dir);
});

test("orchestratePythonPath detects src layout and flat vendor layout", () => {
  const gitLike = mkdtempSync(join(tmpdir(), "twinbox-git-"));
  mkdirSync(join(gitLike, "src", "twinbox_core"), { recursive: true });
  assert.equal(orchestratePythonPath(gitLike), join(gitLike, "src"));
  const flat = mkdtempSync(join(tmpdir(), "twinbox-flat-"));
  mkdirSync(join(flat, "twinbox_core"), { recursive: true });
  assert.equal(orchestratePythonPath(flat), flat);
  assert.equal(orchestratePythonPath(undefined), null);
});

test("resolveOrchestrateInvoke honors TWINBOX_ORCHESTRATE_BIN", () => {
  const prev = process.env.TWINBOX_ORCHESTRATE_BIN;
  process.env.TWINBOX_ORCHESTRATE_BIN = "/opt/bin/my-orch";
  try {
    assert.deepEqual(resolveOrchestrateInvoke({}, "/any/cwd"), {
      command: "/opt/bin/my-orch",
      argsPrefix: [],
      env: {},
    });
  } finally {
    if (prev === undefined) delete process.env.TWINBOX_ORCHESTRATE_BIN;
    else process.env.TWINBOX_ORCHESTRATE_BIN = prev;
  }
});

test("resolvePushSessionTarget uses explicit, env, then default", () => {
  const prevT = process.env.TWINBOX_PUSH_SESSION_TARGET;
  const prevO = process.env.OPENCLAW_SESSION_ID;
  delete process.env.TWINBOX_PUSH_SESSION_TARGET;
  delete process.env.OPENCLAW_SESSION_ID;
  try {
    assert.equal(resolvePushSessionTarget({}), "agent:twinbox:main");
    assert.equal(resolvePushSessionTarget({ session_target: "  sid  " }), "sid");
    process.env.TWINBOX_PUSH_SESSION_TARGET = "from-env";
    assert.equal(resolvePushSessionTarget({}), "from-env");
  } finally {
    if (prevT === undefined) delete process.env.TWINBOX_PUSH_SESSION_TARGET;
    else process.env.TWINBOX_PUSH_SESSION_TARGET = prevT;
    if (prevO === undefined) delete process.env.OPENCLAW_SESSION_ID;
    else process.env.OPENCLAW_SESSION_ID = prevO;
  }
});

test("latestMailNeedsDaytimeSync true on recovery_tool JSON", () => {
  const body = JSON.stringify({
    ok: false,
    recovery_tool: "twinbox_daytime_sync",
    task: "latest-mail",
  });
  assert.equal(latestMailNeedsDaytimeSync(body, "", 0), true);
});

test("latestMailNeedsDaytimeSync false on normal latest-mail JSON", () => {
  const body = JSON.stringify({
    task: "latest-mail",
    summary: "ok",
    urgent_top_k: [],
  });
  assert.equal(latestMailNeedsDaytimeSync(body, "", 0), false);
});

test("latestMailNeedsDaytimeSync true on legacy stderr exit 1", () => {
  assert.equal(
    latestMailNeedsDaytimeSync("", "错误: Missing activity-pulse.json.\nRun sync first.", 1),
    true,
  );
});

test("formatResult prefers stdout then stderr", () => {
  assert.match(
    formatResult({ code: 0, stdout: "ok", stderr: "" }).content[0].text,
    /ok/,
  );
  const err = formatResult({ code: 2, stdout: "", stderr: "bad" });
  assert.match(err.content[0].text, /exit=2/);
  assert.match(err.content[0].text, /bad/);
});

test("registerTwinboxTaskTools registers expected tools and task/thread helpers spawn expected argv", async () => {
  const dir = mkdtempSync(join(tmpdir(), "twinbox-plugin-"));
  const fake = join(dir, "fake-twinbox.sh");
  writeFileSync(fake, "#!/bin/sh\nprintf '%s\\n' \"$@\"\n");
  chmodSync(fake, 0o755);

  const tools = [];
  const api = {
    pluginConfig: { twinboxBin: fake, cwd: dir },
    registerTool(t) {
      tools.push(t);
    },
  };
  registerTwinboxTaskTools(api);

  const names = tools.map((t) => t.name).sort();
  assert.deepEqual(names, [
    "twinbox_config_import_llm_from_openclaw",
    "twinbox_config_set_llm",
    "twinbox_context_import_material",
    "twinbox_daytime_sync",
    "twinbox_latest_mail",
    "twinbox_mailbox_setup",
    "twinbox_mailbox_status",
    "twinbox_onboarding_advance",
    "twinbox_onboarding_confirm_push",
    "twinbox_onboarding_finish_routing_rules",
    "twinbox_onboarding_start",
    "twinbox_onboarding_status",
    "twinbox_push_confirm_onboarding",
    "twinbox_queue_complete",
    "twinbox_queue_dismiss",
    "twinbox_rule_add",
    "twinbox_rule_list",
    "twinbox_rule_remove",
    "twinbox_rule_test",
    "twinbox_schedule_disable",
    "twinbox_schedule_enable",
    "twinbox_schedule_list",
    "twinbox_schedule_reset",
    "twinbox_schedule_update",
    "twinbox_thread_inspect",
    "twinbox_thread_progress",
    "twinbox_todo",
    "twinbox_weekly",
  ]);

  const latest = tools.find((t) => t.name === "twinbox_latest_mail");
  assert.ok(latest);
  const out = await latest.execute();
  assert.equal(out.content[0].type, "text");
  assert.match(out.content[0].text, /task/);
  assert.match(out.content[0].text, /latest-mail/);
  assert.match(out.content[0].text, /--json/);

  const prog = tools.find((t) => t.name === "twinbox_thread_progress");
  assert.ok(prog);
  const pout = await prog.execute({ query: "acme", limit: 3 });
  assert.match(pout.content[0].text, /progress/);
  assert.match(pout.content[0].text, /acme/);
  assert.match(pout.content[0].text, /--limit/);
  assert.match(pout.content[0].text, /3/);

  const inspect = tools.find((t) => t.name === "twinbox_thread_inspect");
  assert.ok(inspect);
  const iout = await inspect.execute({ thread_id: "thread-123" });
  assert.match(iout.content[0].text, /thread/);
  assert.match(iout.content[0].text, /inspect/);
  assert.match(iout.content[0].text, /thread-123/);
  assert.match(iout.content[0].text, /--json/);

  const qComplete = tools.find((t) => t.name === "twinbox_queue_complete");
  assert.ok(qComplete);
  const qcout = await qComplete.execute({ thread_id: "工时填报提醒", action_taken: "已填报" });
  assert.match(qcout.content[0].text, /queue/);
  assert.match(qcout.content[0].text, /complete/);
  assert.match(qcout.content[0].text, /工时填报提醒/);
  assert.match(qcout.content[0].text, /--action-taken/);
  assert.match(qcout.content[0].text, /已填报/);
  assert.match(qcout.content[0].text, /--json/);

  const qDismiss = tools.find((t) => t.name === "twinbox_queue_dismiss");
  assert.ok(qDismiss);
  const qdout = await qDismiss.execute({ thread_id: "rdg货架", reason: "下周再看" });
  assert.match(qdout.content[0].text, /queue/);
  assert.match(qdout.content[0].text, /dismiss/);
  assert.match(qdout.content[0].text, /rdg货架/);
  assert.match(qdout.content[0].text, /--reason/);
  assert.match(qdout.content[0].text, /下周再看/);
  assert.match(qdout.content[0].text, /--json/);

  const scheduleList = tools.find((t) => t.name === "twinbox_schedule_list");
  assert.ok(scheduleList);
  const slout = await scheduleList.execute();
  assert.match(slout.content[0].text, /schedule/);
  assert.match(slout.content[0].text, /list/);
  assert.match(slout.content[0].text, /--json/);

  const scheduleUpdate = tools.find((t) => t.name === "twinbox_schedule_update");
  assert.ok(scheduleUpdate);
  const suout = await scheduleUpdate.execute({ job_name: "daily-refresh", cron: "0 * * * *" });
  assert.match(suout.content[0].text, /schedule/);
  assert.match(suout.content[0].text, /update/);
  assert.match(suout.content[0].text, /daily-refresh/);
  assert.match(suout.content[0].text, /0 \* \* \* \*/);
  assert.match(suout.content[0].text, /--cron/);
  assert.match(suout.content[0].text, /--json/);

  const scheduleReset = tools.find((t) => t.name === "twinbox_schedule_reset");
  assert.ok(scheduleReset);
  const srout = await scheduleReset.execute({ job_name: "daily-refresh" });
  assert.match(srout.content[0].text, /schedule/);
  assert.match(srout.content[0].text, /reset/);
  assert.match(srout.content[0].text, /daily-refresh/);
  assert.match(srout.content[0].text, /--json/);

  const scheduleEnable = tools.find((t) => t.name === "twinbox_schedule_enable");
  assert.ok(scheduleEnable);
  const seout = await scheduleEnable.execute({ job_name: "daily-refresh" });
  assert.match(seout.content[0].text, /schedule/);
  assert.match(seout.content[0].text, /enable/);
  assert.match(seout.content[0].text, /daily-refresh/);
  assert.match(seout.content[0].text, /--json/);

  const scheduleDisable = tools.find((t) => t.name === "twinbox_schedule_disable");
  assert.ok(scheduleDisable);
  const sdout = await scheduleDisable.execute({ job_name: "nightly-full-refresh" });
  assert.match(sdout.content[0].text, /schedule/);
  assert.match(sdout.content[0].text, /disable/);
  assert.match(sdout.content[0].text, /nightly-full-refresh/);
  assert.match(sdout.content[0].text, /--json/);

  const mailboxSetup = tools.find((t) => t.name === "twinbox_mailbox_setup");
  assert.ok(mailboxSetup);
  const msout = await mailboxSetup.execute({ email: "user@example.com", imap_pass: "secret" });
  assert.match(msout.content[0].text, /mailbox/);
  assert.match(msout.content[0].text, /setup/);
  assert.match(msout.content[0].text, /user@example.com/);
  assert.match(msout.content[0].text, /--email/);
  assert.match(msout.content[0].text, /--json/);

  const configSetLlm = tools.find((t) => t.name === "twinbox_config_set_llm");
  assert.ok(configSetLlm);
  const clout = await configSetLlm.execute({ api_key: "sk-test", provider: "anthropic" });
  assert.match(clout.content[0].text, /config/);
  assert.match(clout.content[0].text, /set-llm/);
  assert.match(clout.content[0].text, /anthropic/);
  assert.match(clout.content[0].text, /--json/);

  const importOc = tools.find((t) => t.name === "twinbox_config_import_llm_from_openclaw");
  assert.ok(importOc);
  const imout = await importOc.execute({ dry_run: true, openclaw_json: "/tmp/oc.json" });
  assert.match(imout.content[0].text, /import-llm-from-openclaw/);
  assert.match(imout.content[0].text, /--dry-run/);
  assert.match(imout.content[0].text, /--openclaw-json/);
  assert.match(imout.content[0].text, /--json/);
});
