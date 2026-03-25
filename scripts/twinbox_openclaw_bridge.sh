#!/usr/bin/env bash
# Stable host bridge wrapper for OpenClaw system-event payloads.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/python_common.sh"
export TZ="${TZ:-Asia/Shanghai}"

CODE_ROOT="${TWINBOX_CODE_ROOT:-$(cd "${SCRIPT_DIR}/.." && pwd -P)}"
STATE_ROOT="${TWINBOX_STATE_ROOT:-${TWINBOX_CANONICAL_ROOT:-${CODE_ROOT}}}"

usage() {
  cat <<'EOF'
Usage:
  scripts/twinbox_openclaw_bridge.sh --event-text TEXT [--dry-run] [--format json|text]
  scripts/twinbox_openclaw_bridge.sh --event-file PATH [--dry-run] [--format json|text]
  echo 'twinbox.schedule:daytime-sync' | scripts/twinbox_openclaw_bridge.sh [--dry-run]
EOF
}

bridge_args=()
if [[ $# -ge 2 && "$1" == "--event-text" ]]; then
  bridge_args=(--event-text "$2")
  shift 2
elif [[ $# -ge 2 && "$1" == "--event-file" ]]; then
  bridge_args=(--event-file "$2")
  shift 2
elif [[ ! -t 0 ]]; then
  event_text="$(cat)"
  bridge_args=(--event-text "${event_text}")
else
  usage >&2
  exit 1
fi

cd "${STATE_ROOT}"
export TWINBOX_CODE_ROOT="${CODE_ROOT}"
export TWINBOX_STATE_ROOT="${STATE_ROOT}"
export TWINBOX_CANONICAL_ROOT="${STATE_ROOT}"

extra_args=()
if [[ -n "${TWINBOX_BRIDGE_FORMAT:-}" ]]; then
  extra_args+=(--format "${TWINBOX_BRIDGE_FORMAT}")
fi

exec "${SCRIPT_DIR}/twinbox_orchestrate.sh" bridge "${bridge_args[@]}" "${extra_args[@]}" "$@"
