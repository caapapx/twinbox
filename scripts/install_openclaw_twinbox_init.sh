#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CODE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/twinbox"
CODE_ROOT_FILE="${CONFIG_DIR}/code-root"
STATE_ROOT_FILE="${CONFIG_DIR}/state-root"
CANONICAL_ROOT_FILE="${CONFIG_DIR}/canonical-root"

# Default state root: ~/.twinbox (separate from code repo, never committed to git)
# Override with TWINBOX_STATE_ROOT env var if needed
STATE_ROOT="${TWINBOX_STATE_ROOT:-${HOME}/.twinbox}"

LOG_DIR="${STATE_ROOT}/logs"

usage() {
  cat <<'EOF'
Usage:
  scripts/install_openclaw_twinbox_init.sh [--verify]

One-time Twinbox bootstrap:
  1. Create state root at ~/.twinbox (runtime data: .env, phase outputs, logs)
  2. Persist ~/.config/twinbox/code-root  -> this repo
  3. Persist ~/.config/twinbox/state-root -> ~/.twinbox
  4. Keep   ~/.config/twinbox/canonical-root as legacy alias

Options:
  --verify    Also run mailbox preflight from OpenClaw workspace (requires
              OpenClaw to already be configured with a workspace)
  --help      Show this message

Override state root location:
  TWINBOX_STATE_ROOT=/custom/path bash scripts/install_openclaw_twinbox_init.sh
EOF
}

VERIFY=0
for arg in "$@"; do
  case "$arg" in
    --help|-h) usage; exit 0 ;;
    --verify)  VERIFY=1 ;;
    *) echo "Unknown argument: $arg" >&2; usage; exit 1 ;;
  esac
done

# Create state root and log dir
mkdir -p "${STATE_ROOT}" "${LOG_DIR}"

# Write config files
mkdir -p "${CONFIG_DIR}"
printf '%s\n' "${CODE_ROOT}"  > "${CODE_ROOT_FILE}"
printf '%s\n' "${STATE_ROOT}" > "${STATE_ROOT_FILE}"
printf '%s\n' "${STATE_ROOT}" > "${CANONICAL_ROOT_FILE}"

echo "Wrote Twinbox roots:"
echo "  ${CODE_ROOT_FILE}      -> ${CODE_ROOT}"
echo "  ${STATE_ROOT_FILE}     -> ${STATE_ROOT}"
echo "  ${CANONICAL_ROOT_FILE} -> ${STATE_ROOT} (legacy compatibility)"
echo ""
echo "State root created: ${STATE_ROOT}"
echo "  .env and runtime data will be stored here (not in the code repo)"

if [[ "${VERIFY}" -eq 1 ]]; then
  OPENCLAW_WORKSPACE="${OPENCLAW_WORKSPACE:-${HOME}/.openclaw/workspace}"
  if [[ ! -d "${OPENCLAW_WORKSPACE}" ]]; then
    echo "" >&2
    echo "Error: --verify requires OpenClaw workspace at ${OPENCLAW_WORKSPACE}" >&2
    echo "Run without --verify first, then configure OpenClaw, then re-run with --verify." >&2
    exit 1
  fi

  echo ""
  echo "Verifying mailbox preflight from OpenClaw workspace..."
  (
    cd "${OPENCLAW_WORKSPACE}"
    "${CODE_ROOT}/.venv/bin/twinbox" mailbox preflight --json \
      2> "${LOG_DIR}/init-preflight.stderr.log"
  )
  echo "Preflight log: ${LOG_DIR}/init-preflight.stderr.log"
fi
