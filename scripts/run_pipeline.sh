#!/usr/bin/env bash
# run_pipeline.sh — Phase 1-4 loading → thinking，Phase 4 默认并行
#
# 用法：
#   bash scripts/run_pipeline.sh              # 全流程（Phase 4 并行）
#   bash scripts/run_pipeline.sh --phase 2    # 只跑 Phase 2
#   bash scripts/run_pipeline.sh --serial     # Phase 4 用串行模式
#   bash scripts/run_pipeline.sh --dry-run    # 只打印，不执行

set -euo pipefail

export TZ="Asia/Shanghai"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false
PHASE=""
SERIAL=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase) PHASE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --serial) SERIAL=true; shift ;;
    *)
      echo "Unknown option: $1" >&2
      echo "Usage: bash scripts/run_pipeline.sh [--phase N] [--dry-run] [--serial]" >&2
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
  if [[ "$n" == "4" && "$SERIAL" == "false" ]]; then
    run_step "Phase 4 Thinking (parallel)" "$SCRIPT_DIR/phase4_thinking_parallel.sh"
  else
    run_step "Phase $n Thinking" "$SCRIPT_DIR/phase${n}_thinking.sh"
  fi
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
