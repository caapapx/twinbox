#!/usr/bin/env bash
# Unified entrypoint for Gastown Phase 4 steps.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

usage() {
  cat <<'USAGE'
Usage: bash scripts/phase4_gastown.sh <command> [args...]
Commands:
  loading
  think-urgent
  think-sla
  think-brief
  merge
  roots
USAGE
}

COMMAND="${1:-}"
if [[ -z "${COMMAND}" ]]; then
  usage
  exit 1
fi
shift || true

case "${COMMAND}" in
  loading) exec bash "${SCRIPT_DIR}/phase4_loading.sh" "$@" ;;
  think-urgent) exec bash "${SCRIPT_DIR}/phase4_think_urgent.sh" "$@" ;;
  think-sla) exec bash "${SCRIPT_DIR}/phase4_think_sla.sh" "$@" ;;
  think-brief) exec bash "${SCRIPT_DIR}/phase4_think_brief.sh" "$@" ;;
  merge) exec bash "${SCRIPT_DIR}/phase4_merge.sh" "$@" ;;
  roots)
    source "${SCRIPT_DIR}/twinbox_paths.sh"
    twinbox_init_roots "${BASH_SOURCE[0]}"
    echo "code_root=${TWINBOX_CODE_ROOT}"
    echo "canonical_root=${TWINBOX_CANONICAL_ROOT}"
    ;;
  -h|--help)
    usage
    ;;
  *)
    echo "Unknown command: ${COMMAND}" >&2
    usage
    exit 1
    ;;
esac
