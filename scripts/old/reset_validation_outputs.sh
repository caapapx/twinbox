#!/usr/bin/env bash
# Reset generated validation outputs while preserving human-authored context.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

remove_path() {
  local path="$1"
  if [[ -e "${path}" ]]; then
    rm -rf "${path}"
    echo "removed ${path#${ROOT_DIR}/}"
  fi
}

remove_path "${ROOT_DIR}/runtime/context/phase1-context.json"
remove_path "${ROOT_DIR}/runtime/context/raw"
remove_path "${ROOT_DIR}/runtime/validation/phase-1"
remove_path "${ROOT_DIR}/runtime/validation/phase-2"
remove_path "${ROOT_DIR}/runtime/validation/phase-3"
remove_path "${ROOT_DIR}/runtime/validation/phase-4"
remove_path "${ROOT_DIR}/runtime/validation/preflight"

remove_path "${ROOT_DIR}/docs/validation/phase-1-report.md"
remove_path "${ROOT_DIR}/docs/validation/phase-2-report.md"
remove_path "${ROOT_DIR}/docs/validation/phase-3-report.md"
remove_path "${ROOT_DIR}/docs/validation/phase-4-report.md"
remove_path "${ROOT_DIR}/docs/validation/preflight-mailbox-smoke-report.md"
remove_path "${ROOT_DIR}/docs/validation/diagrams/phase-1-mailbox-overview.mmd"
remove_path "${ROOT_DIR}/docs/validation/diagrams/phase-1-sender-network.mmd"
remove_path "${ROOT_DIR}/docs/validation/diagrams/phase-2-relationship-map.mmd"
remove_path "${ROOT_DIR}/docs/validation/diagrams/phase-3-lifecycle-overview.mmd"
remove_path "${ROOT_DIR}/docs/validation/diagrams/phase-3-thread-state-machine.mmd"

mkdir -p \
  "${ROOT_DIR}/runtime/context/raw" \
  "${ROOT_DIR}/runtime/validation" \
  "${ROOT_DIR}/docs/validation/diagrams"

echo "validation outputs reset complete"
