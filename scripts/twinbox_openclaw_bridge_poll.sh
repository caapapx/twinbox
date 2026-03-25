#!/usr/bin/env bash
# Host-side poller for OpenClaw cron/system-event runs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/python_common.sh"

usage() {
  cat <<'EOF'
Usage:
  scripts/twinbox_openclaw_bridge_poll.sh [--dry-run] [--format json|text] [--limit N] [--openclaw-bin PATH]

Poll OpenClaw cron run history, find newly finished Twinbox bridge events,
and dispatch them through `twinbox-orchestrate bridge`.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ -n "${TWINBOX_CODE_ROOT:-}" ]]; then
  CODE_ROOT="${TWINBOX_CODE_ROOT}"
else
  CODE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
  export TWINBOX_CODE_ROOT="${CODE_ROOT}"
fi

if [[ -n "${TWINBOX_STATE_ROOT:-}" ]]; then
  STATE_ROOT="${TWINBOX_STATE_ROOT}"
elif [[ -n "${TWINBOX_CANONICAL_ROOT:-}" ]]; then
  STATE_ROOT="${TWINBOX_CANONICAL_ROOT}"
else
  STATE_ROOT="${CODE_ROOT}"
  export TWINBOX_STATE_ROOT="${STATE_ROOT}"
  export TWINBOX_CANONICAL_ROOT="${STATE_ROOT}"
fi

cd "${STATE_ROOT}"

exec "${SCRIPT_DIR}/twinbox_orchestrate.sh" bridge-poll "$@"
