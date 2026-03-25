#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CODE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/twinbox"
CODE_ROOT_FILE="${CONFIG_DIR}/code-root"
STATE_ROOT_FILE="${CONFIG_DIR}/state-root"
CANONICAL_ROOT_FILE="${CONFIG_DIR}/canonical-root"
OPENCLAW_WORKSPACE="${OPENCLAW_WORKSPACE:-${HOME}/.openclaw/workspace}"

usage() {
  cat <<'EOF'
Usage:
  scripts/install_openclaw_twinbox_init.sh [--no-verify]

One-time OpenClaw/Twinbox bootstrap:
1. Persist ~/.config/twinbox/code-root
2. Persist ~/.config/twinbox/state-root
3. Keep ~/.config/twinbox/canonical-root as legacy compatibility alias
4. Optionally verify that preflight still resolves the configured roots from ~/.openclaw/workspace
EOF
}

VERIFY=1
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ "${1:-}" == "--no-verify" ]]; then
  VERIFY=0
fi

mkdir -p "${CONFIG_DIR}"
printf '%s\n' "${CODE_ROOT}" > "${CODE_ROOT_FILE}"
printf '%s\n' "${CODE_ROOT}" > "${STATE_ROOT_FILE}"
printf '%s\n' "${CODE_ROOT}" > "${CANONICAL_ROOT_FILE}"

echo "Wrote Twinbox roots:"
echo "  ${CODE_ROOT_FILE} -> ${CODE_ROOT}"
echo "  ${STATE_ROOT_FILE} -> ${CODE_ROOT}"
echo "  ${CANONICAL_ROOT_FILE} -> ${CODE_ROOT} (legacy compatibility)"

if [[ "${VERIFY}" -eq 1 ]]; then
  if [[ ! -d "${OPENCLAW_WORKSPACE}" ]]; then
    echo "OpenClaw workspace not found: ${OPENCLAW_WORKSPACE}" >&2
    exit 1
  fi

  echo ""
  echo "Verifying Twinbox root resolution from OpenClaw workspace..."
  (
    cd "${OPENCLAW_WORKSPACE}"
    "${CODE_ROOT}/scripts/twinbox" mailbox preflight --json
  )
fi
