#!/usr/bin/env bash
# run_pipeline.sh — 顺序执行 Phase 1-4 的 loading → thinking
# 纯 bash 串行 fallback，不依赖 gastown。
#
# 用法：
#   bash scripts/run_pipeline.sh              # 全流程
#   bash scripts/run_pipeline.sh --phase 2    # 只跑 Phase 2
#   bash scripts/run_pipeline.sh --dry-run    # 只打印，不执行

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false
PHASE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase)
      PHASE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: bash scripts/run_pipeline.sh [--phase N] [--dry-run]" >&2
      exit 1
      ;;
  esac
done

run_step() {
  local label="$1"
  local script="$2"
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[dry-run] $label: bash $script"
  else
    echo "=== $label ==="
    bash "$script"
    echo ""
  fi
}

run_phase() {
  local n="$1"
  run_step "Phase $n Loading"  "$SCRIPT_DIR/phase${n}_loading.sh"
  run_step "Phase $n Thinking" "$SCRIPT_DIR/phase${n}_thinking.sh"
}

if [[ -n "$PHASE" ]]; then
  if [[ "$PHASE" =~ ^[1-4]$ ]]; then
    run_phase "$PHASE"
  else
    echo "Error: --phase must be 1-4, got '$PHASE'" >&2
    exit 1
  fi
else
  for n in 1 2 3 4; do
    run_phase "$n"
  done
fi

if [[ "$DRY_RUN" == "false" ]]; then
  echo "=== Pipeline complete ==="
fi
