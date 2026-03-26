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
    "twinbox_latest_mail",
    "twinbox_mailbox_status",
    "twinbox_rule_add",
    "twinbox_rule_list",
    "twinbox_rule_remove",
    "twinbox_rule_test",
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
});
