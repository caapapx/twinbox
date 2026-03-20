#!/usr/bin/env bash
# Phase 2 Thinking: LLM-based persona + business profile inference
# Reads Phase 1 outputs + context pack, calls LLM for real inference.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

CODE_ROOT="${TWINBOX_CODE_ROOT}"
STATE_ROOT="${TWINBOX_CANONICAL_ROOT}"
PHASE2_DIR="${STATE_ROOT}/runtime/validation/phase-2"
DOC_DIR="${STATE_ROOT}/docs/validation"
DIAGRAM_DIR="${DOC_DIR}/diagrams"
CONTEXT_PACK="${PHASE2_DIR}/context-pack.json"
source "${CODE_ROOT}/scripts/llm_common.sh"

DRY_RUN=false
usage() {
  cat <<'USAGE'
Usage:
  bash scripts/phase2_thinking.sh [options]

Options:
  --dry-run    Print prompt without calling LLM
  -h, --help   Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

mkdir -p "${PHASE2_DIR}" "${DOC_DIR}" "${DIAGRAM_DIR}"

if [[ ! -f "${CONTEXT_PACK}" ]]; then
  echo "Missing: ${CONTEXT_PACK}"
  echo "Run: bash scripts/phase2_loading.sh first"
  exit 1
fi

cmd=(
  _twinbox_python -m twinbox_core.phase2_persona
  --context "${CONTEXT_PACK}"
  --output-dir "${PHASE2_DIR}"
  --doc-dir "${DOC_DIR}"
  --diagram-dir "${DIAGRAM_DIR}"
  --env-file "${STATE_ROOT}/.env"
)

if [[ "${DRY_RUN}" == "true" ]]; then
  cmd+=(--dry-run)
fi

"${cmd[@]}"
