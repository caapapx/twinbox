#!/usr/bin/env bash
# Phase 1 Incremental entrypoint for daytime-sync.
# Current bootstrap behavior falls back to the existing full Phase 1 loader
# until the IMAP fetch + merge path is fully wired end-to-end.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

exec bash "${SCRIPT_DIR}/phase1_loading.sh" "$@"
