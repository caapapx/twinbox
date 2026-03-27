import { chmodSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import { registerTwinboxTaskTools, toolOpts, formatResult } from "./register-twinbox-tools.mjs";

test("toolOpts uses env TWINBOX_CODE_ROOT when cwd omitted", () => {
  const prev = process.env.TWINBOX_CODE_ROOT;
  process.env.TWINBOX_CODE_ROOT = "/tmp/tb-root";
  try {
    assert.deepEqual(toolOpts({ twinboxBin: "twinbox" }), {
      twinboxBin: "twinbox",
      cwd: "/tmp/tb-root",
    });
  } finally {
    if (prev === undefined) {
      delete process.env.TWINBOX_CODE_ROOT;
    } else {
      process.env.TWINBOX_CODE_ROOT = prev;
    }
  }
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
    "twinbox_config_set_llm",
    "twinbox_latest_mail",
    "twinbox_mailbox_setup",
    "twinbox_mailbox_status",
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
});
