#!/usr/bin/env bash
# Phase 4 Merge: 合并 3 个子任务的 raw JSON → YAML/MD 输出
# 纯合并，不调 LLM。前置条件：3 个 *-raw.json 已存在。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

CODE_ROOT="${TWINBOX_CODE_ROOT}"
STATE_ROOT="${TWINBOX_CANONICAL_ROOT}"
PHASE4_DIR="${STATE_ROOT}/runtime/validation/phase-4"
DOC_DIR="${STATE_ROOT}/docs/validation"
source "${CODE_ROOT}/scripts/llm_common.sh"
mkdir -p "${PHASE4_DIR}" "${DOC_DIR}"

for f in urgent-pending-raw.json sla-risks-raw.json weekly-brief-raw.json; do
  if [[ ! -f "${PHASE4_DIR}/${f}" ]]; then
    echo "Missing ${f}. Run think sub-tasks first." >&2; exit 1
  fi
done

_twinbox_python -m twinbox_core.phase4_value merge \
  --output-dir "${PHASE4_DIR}" \
  --doc-dir "${DOC_DIR}" \
  --env-file "${STATE_ROOT}/.env"
