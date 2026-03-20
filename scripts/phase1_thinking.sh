#!/usr/bin/env bash
# Phase 1 Thinking: LLM batch intent classification
# Input:  runtime/context/phase1-context.json
# Output: runtime/validation/phase-1/intent-classification.json
#         runtime/validation/phase-1/intent-report.md
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

CODE_ROOT="${TWINBOX_CODE_ROOT}"
STATE_ROOT="${TWINBOX_CANONICAL_ROOT}"
ENV_FILE="${STATE_ROOT}/.env"
CONTEXT_PACK="${STATE_ROOT}/runtime/context/phase1-context.json"
OUTPUT_DIR="${STATE_ROOT}/runtime/validation/phase-1"
BATCH_SIZE=15
MODEL=""
DRY_RUN=false

source "${CODE_ROOT}/scripts/llm_common.sh"

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/phase1_thinking.sh [options]

Reads phase1-context.json, calls LLM for batch intent classification.
Requires: LLM_API_KEY or ANTHROPIC_API_KEY in .env or environment.

Options:
  --context <path>    Override context-pack path
  --batch-size <n>    Envelopes per LLM call (default: 15)
  --model <name>      Override backend default model
  --dry-run           Print prompts without calling API
  -h, --help          Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --context) CONTEXT_PACK="${2:-}"; shift 2 ;;
    --batch-size) BATCH_SIZE="${2:-}"; shift 2 ;;
    --model) MODEL="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

if [[ ! -f "${CONTEXT_PACK}" ]]; then
  echo "Error: context-pack not found at ${CONTEXT_PACK}"
  echo "Run scripts/phase1_loading.sh first."
  exit 1
fi

mkdir -p "${OUTPUT_DIR}"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  source "${ENV_FILE}"
  set +a
fi

if [[ "${DRY_RUN}" != "true" ]]; then
  init_llm_backend "${ENV_FILE}" || exit 1
fi

echo "Phase 1 Thinking: LLM intent classification"
if [[ -n "${MODEL}" ]]; then
  echo "  Model override: ${MODEL}"
fi
echo "  Context: ${CONTEXT_PACK}"
echo "  Batch size: ${BATCH_SIZE}"

cmd=(
  python3 -m twinbox_core.phase1_intent
  --context "${CONTEXT_PACK}"
  --output-dir "${OUTPUT_DIR}"
  --batch-size "${BATCH_SIZE}"
  --env-file "${ENV_FILE}"
)

if [[ -n "${MODEL}" ]]; then
  cmd+=(--model "${MODEL}")
fi

if [[ "${DRY_RUN}" == "true" ]]; then
  cmd+=(--dry-run)
fi

PYTHONPATH="${CODE_ROOT}/python/src${PYTHONPATH:+:${PYTHONPATH}}" "${cmd[@]}"

echo ""
echo "Phase 1 Thinking complete."
echo "  Output: runtime/validation/phase-1/intent-classification.json"
echo "  Report: runtime/validation/phase-1/intent-report.md"
