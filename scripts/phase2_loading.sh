#!/usr/bin/env bash
# Phase 2 Loading: read Phase 1 outputs + prepare context for LLM persona inference
# Deterministic, no LLM.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"
source "${SCRIPT_DIR}/python_common.sh"

STATE_ROOT="${TWINBOX_STATE_ROOT:-${TWINBOX_CANONICAL_ROOT}}"
PHASE2_DIR="${STATE_ROOT}/runtime/validation/phase-2"
DOC_DIR="${STATE_ROOT}/docs/validation"
DIAGRAM_DIR="${DOC_DIR}/diagrams"

mkdir -p "${PHASE2_DIR}" "${DOC_DIR}" "${DIAGRAM_DIR}"

_twinbox_python -m twinbox_core.context_builder phase2 --state-root "${STATE_ROOT}"

echo ""
echo "Phase 2 loading complete."
echo "Output: ${PHASE2_DIR}/context-pack.json"
echo ""
echo "Next: bash scripts/phase2_thinking.sh"
