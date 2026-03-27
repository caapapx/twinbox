#!/usr/bin/env bash
# Phase 4 Loading shim: delegate to Python loading pipeline.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

STATE_ROOT="${TWINBOX_STATE_ROOT:-${TWINBOX_CANONICAL_ROOT}}"
source "${SCRIPT_DIR}/python_common.sh"

_twinbox_python -m twinbox_core.loading_pipeline phase4 --state-root "${STATE_ROOT}" "$@"
