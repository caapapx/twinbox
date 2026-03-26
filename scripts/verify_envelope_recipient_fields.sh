#!/usr/bin/env bash
# Quick probe: does envelope JSON include To/Cc (for envelope-based recipient_role)?
# Usage:
#   ./scripts/verify_envelope_recipient_fields.sh \
#     --json-file "$TWINBOX_STATE_ROOT/runtime/validation/phase-1/raw/envelopes-merged.json"
#   ./scripts/verify_envelope_recipient_fields.sh --live --account myTwinbox --config "$TWINBOX_STATE_ROOT/runtime/himalaya/config.toml"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CODE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
export PYTHONPATH="${CODE_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

exec python3 -m twinbox_core.envelope_recipient_probe "$@"
