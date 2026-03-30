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
      twinboxBin: {
        type: "string",
        description:
          "Optional Twinbox executable path. Prefer an absolute path on the Gateway host. If unset, the plugin auto-detects <cwd>/scripts/twinbox before falling back to twinbox from PATH.",
      },
      cwd: {
        type: "string",
        description:
          "Twinbox code root. Used as the working directory and for auto-detecting <cwd>/scripts/twinbox when twinboxBin is unset.",
      },
    },
  },
  register(api) {
    registerTwinboxTaskTools(api);
  },
};
