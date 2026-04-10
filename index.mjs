/**
 * Twinbox OpenClaw plugin entry point.
 */
import { registerTwinboxTools } from "./register-tools.mjs";

export default function activate(api) {
  registerTwinboxTools(api);
}
