#!/usr/bin/env bash
# Seed ~/.twinbox (or TWINBOX_STATE_ROOT) with 30 synthetic envelopes + phase4 queues + activity-pulse.
# For OpenClaw modular testing: run this on the host, then use twinbox task commands in chat.
set -euo pipefail
ROOT="${TWINBOX_STATE_ROOT:-$HOME/.twinbox}"
COUNT="${1:-30}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="${REPO_ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m twinbox_core.modular_mail_sim --state-root "$ROOT" --count "$COUNT" --json
