#!/usr/bin/env bash
# Phase 4 子任务: sla-risks (可并行)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

CODE_ROOT="${TWINBOX_CODE_ROOT}"
STATE_ROOT="${TWINBOX_STATE_ROOT:-${TWINBOX_CANONICAL_ROOT}}"
PHASE4_DIR="${STATE_ROOT}/runtime/validation/phase-4"
CONTEXT_PACK="${PHASE4_DIR}/context-pack.json"

source "${CODE_ROOT}/scripts/llm_common.sh"

if [[ ! -f "${CONTEXT_PACK}" ]]; then
  echo "Missing: ${CONTEXT_PACK}" >&2
  echo "Run: bash scripts/phase4_loading.sh first" >&2
  exit 1
fi

_twinbox_python -m twinbox_core.phase4_value think-sla \
  --context "${CONTEXT_PACK}" \
  --output-dir "${PHASE4_DIR}" \
  --env-file "${STATE_ROOT}/.env"
