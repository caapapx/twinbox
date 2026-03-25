#!/usr/bin/env bash
# Phase 4 Thinking (并行版): 3 个子任务并行 → 合并输出
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

CODE_ROOT="${TWINBOX_CODE_ROOT}"
STATE_ROOT="${TWINBOX_STATE_ROOT:-${TWINBOX_CANONICAL_ROOT}}"
PHASE4_DIR="${STATE_ROOT}/runtime/validation/phase-4"
DOC_DIR="${STATE_ROOT}/docs/validation"
mkdir -p "${PHASE4_DIR}" "${DOC_DIR}"

if [[ ! -f "${PHASE4_DIR}/context-pack.json" ]]; then
  echo "Missing context-pack. Run phase4_loading.sh first." >&2; exit 1
fi

echo "Phase 4 Thinking (parallel mode): launching 3 sub-tasks..."

# 并行启动 3 个子任务
bash "${CODE_ROOT}/scripts/phase4_think_urgent.sh" &
PID_URGENT=$!
bash "${CODE_ROOT}/scripts/phase4_think_sla.sh" &
PID_SLA=$!
bash "${CODE_ROOT}/scripts/phase4_think_brief.sh" &
PID_BRIEF=$!

# 等待全部完成
FAIL=0
for pid in $PID_URGENT $PID_SLA $PID_BRIEF; do
  wait "$pid" || FAIL=$((FAIL+1))
done
if [[ $FAIL -gt 0 ]]; then
  echo "ERROR: $FAIL sub-task(s) failed" >&2; exit 1
fi

echo "All sub-tasks done. Merging outputs..."

source "${CODE_ROOT}/scripts/llm_common.sh"

for f in urgent-pending-raw.json sla-risks-raw.json weekly-brief-raw.json; do
  if [[ ! -f "${PHASE4_DIR}/${f}" ]]; then
    echo "Missing ${f}. Run think sub-tasks first." >&2
    exit 1
  fi
done

_twinbox_python -m twinbox_core.phase4_value merge \
  --output-dir "${PHASE4_DIR}" \
  --doc-dir "${DOC_DIR}" \
  --env-file "${STATE_ROOT}/.env"
