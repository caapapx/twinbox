#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/python_common.sh"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

ROOT_DIR="${TWINBOX_CANONICAL_ROOT}"
_twinbox_python -m twinbox_core.mailbox render-config --state-root "${ROOT_DIR}"
