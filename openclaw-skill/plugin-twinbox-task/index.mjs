/**
 * OpenClaw tool plugin: run `twinbox task … --json` without relying on the model
 * to chain read(SKILL.md) -> command execution. Use when hosted agents stop
 * after a skill read.
 *
 * Keep the entry shape as a plain object so it can load on OpenClaw 2026.3.23
 * without depending on package-local SDK import resolution.
 */
import { registerTwinboxTaskTools } from "./register-twinbox-tools.mjs";

export default {
  id: "twinbox-task-tools",
  name: "Twinbox task tools",
  description:
    "Deterministic read-only Twinbox task CLI tools (JSON). Prefer these for mail summaries and queues.",
  configSchema: {
    type: "object",
    additionalProperties: false,
    properties: {
      twinboxBin: { type: "string", default: "twinbox" },
      cwd: { type: "string" },
    },
  },
  register(api) {
    registerTwinboxTaskTools(api);
  },
};
