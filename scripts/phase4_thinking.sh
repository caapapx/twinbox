#!/usr/bin/env bash
# Phase 4 Thinking: LLM-based daily value outputs
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

CODE_ROOT="${TWINBOX_CODE_ROOT}"
STATE_ROOT="${TWINBOX_STATE_ROOT:-${TWINBOX_CANONICAL_ROOT}}"
PHASE4_DIR="${STATE_ROOT}/runtime/validation/phase-4"
DOC_DIR="${STATE_ROOT}/docs/validation"
CONTEXT_PACK="${PHASE4_DIR}/context-pack.json"
source "${CODE_ROOT}/scripts/llm_common.sh"

DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) echo "Usage: bash scripts/phase4_thinking.sh [--dry-run]"; exit 0 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

mkdir -p "${PHASE4_DIR}" "${DOC_DIR}"

if [[ ! -f "${CONTEXT_PACK}" ]]; then
  echo "Missing: ${CONTEXT_PACK}"
  echo "Run: bash scripts/phase4_loading.sh first"
  exit 1
fi

cmd=(
  _twinbox_python -m twinbox_core.phase4_value single-run
  --context "${CONTEXT_PACK}"
  --output-dir "${PHASE4_DIR}"
  --doc-dir "${DOC_DIR}"
  --env-file "${STATE_ROOT}/.env"
  --max-tokens "${LLM_MAX_TOKENS:-8192}"
)

if [[ "${DRY_RUN}" == "true" ]]; then
  cmd+=(--dry-run)
fi

"${cmd[@]}"
