#!/usr/bin/env bash
# run_pipeline.sh — backward-compatible wrapper over the shared orchestration CLI
#
# 用法：
#   bash scripts/run_pipeline.sh              # 全流程（Phase 4 并行）
#   bash scripts/run_pipeline.sh --phase 2    # 只跑 Phase 2
#   bash scripts/run_pipeline.sh --serial     # Phase 4 用串行模式
#   bash scripts/run_pipeline.sh --dry-run    # 只打印，不执行

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

exec bash "${SCRIPT_DIR}/twinbox_orchestrate.sh" run "$@"
