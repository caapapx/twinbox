#!/usr/bin/env bash
# Stable orchestration CLI for local runs, skill adapters, and future backends.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/python_common.sh"
export TZ="${TZ:-Asia/Shanghai}"

_twinbox_python -m twinbox_core.orchestration "$@"
