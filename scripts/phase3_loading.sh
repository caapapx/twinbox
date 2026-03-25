#!/usr/bin/env bash
# Phase 3 Loading: prepare context for lifecycle modeling
# Reads Phase 1/2 outputs + human context, builds context pack.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"
source "${SCRIPT_DIR}/python_common.sh"

STATE_ROOT="${TWINBOX_STATE_ROOT:-${TWINBOX_CANONICAL_ROOT}}"
PHASE3_DIR="${STATE_ROOT}/runtime/validation/phase-3"
DOC_DIR="${STATE_ROOT}/docs/validation"
DIAGRAM_DIR="${DOC_DIR}/diagrams"

mkdir -p "${PHASE3_DIR}" "${DOC_DIR}" "${DIAGRAM_DIR}"

_twinbox_python -m twinbox_core.context_builder phase3 --state-root "${STATE_ROOT}"

echo ""
echo "Phase 3 loading complete."
echo "Output: ${PHASE3_DIR}/context-pack.json"
echo ""
echo "Next: bash scripts/phase3_thinking.sh"
