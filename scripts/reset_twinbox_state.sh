#!/usr/bin/env bash
# Reset Twinbox runtime state only.
# Removes: runtime/, OpenClaw twinbox sessions.
# Preserves: CLI install, ~/.config/twinbox/ roots, openclaw.json, skill file,
#            systemd units, cron jobs.
#
# Usage:
#   bash scripts/reset_twinbox_state.sh [--dry-run]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

# Read state root from config file (defaults to ~/.twinbox)
_STATE_ROOT_FILE="${XDG_CONFIG_HOME:-${HOME}/.config}/twinbox/state-root"
if [[ -f "${_STATE_ROOT_FILE}" ]]; then
  STATE_ROOT="$(tr -d '\n' < "${_STATE_ROOT_FILE}")"
else
  STATE_ROOT="${HOME}/.twinbox"
fi
OPENCLAW_SESSIONS_DIR="${HOME}/.openclaw/agents/twinbox/sessions"

DRY_RUN=0
for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    --help|-h)
      echo "Usage: bash scripts/reset_twinbox_state.sh [--dry-run]"
      exit 0 ;;
  esac
done

run() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

echo "=== Twinbox state reset ==="
[[ "${DRY_RUN}" -eq 1 ]] && echo "(dry-run mode — no changes will be made)"
echo ""

# 1. Remove runtime/
echo "--- [1/2] runtime state ---"
RUNTIME_DIR="${STATE_ROOT}/runtime"
if [[ -d "${RUNTIME_DIR}" ]]; then
  echo "Removing ${RUNTIME_DIR}"
  run rm -rf "${RUNTIME_DIR}"
else
  echo "Runtime directory not found."
fi

# 2. Remove OpenClaw twinbox sessions
echo ""
echo "--- [2/2] OpenClaw twinbox sessions ---"
if [[ -d "${OPENCLAW_SESSIONS_DIR}" ]]; then
  echo "Removing ${OPENCLAW_SESSIONS_DIR}"
  run rm -rf "${OPENCLAW_SESSIONS_DIR}"
else
  echo "No sessions directory found."
fi

echo ""
echo "=== State reset complete ==="
[[ "${DRY_RUN}" -eq 1 ]] && echo "(dry-run — no changes were made)"
