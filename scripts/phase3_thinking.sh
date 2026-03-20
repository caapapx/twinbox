#!/usr/bin/env bash
# Phase 3 Thinking: LLM-based lifecycle modeling
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

CODE_ROOT="${TWINBOX_CODE_ROOT}"
STATE_ROOT="${TWINBOX_CANONICAL_ROOT}"
PHASE3_DIR="${STATE_ROOT}/runtime/validation/phase-3"
DOC_DIR="${STATE_ROOT}/docs/validation"
DIAGRAM_DIR="${DOC_DIR}/diagrams"
CONTEXT_PACK="${PHASE3_DIR}/context-pack.json"
source "${CODE_ROOT}/scripts/llm_common.sh"

DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) echo "Usage: bash scripts/phase3_thinking.sh [--dry-run]"; exit 0 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

mkdir -p "${PHASE3_DIR}" "${DOC_DIR}" "${DIAGRAM_DIR}"

if [[ ! -f "${CONTEXT_PACK}" ]]; then
  echo "Missing: ${CONTEXT_PACK}"
  echo "Run: bash scripts/phase3_loading.sh first"
  exit 1
fi

cmd=(
  _twinbox_python -m twinbox_core.phase3_lifecycle
  --context "${CONTEXT_PACK}"
  --output-dir "${PHASE3_DIR}"
  --doc-dir "${DOC_DIR}"
  --diagram-dir "${DIAGRAM_DIR}"
  --env-file "${STATE_ROOT}/.env"
)

if [[ "${DRY_RUN}" == "true" ]]; then
  cmd+=(--dry-run)
fi

"${cmd[@]}"
