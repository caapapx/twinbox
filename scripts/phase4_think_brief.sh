#!/usr/bin/env bash
# Phase 4 子任务: weekly-brief (可并行)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

CODE_ROOT="${TWINBOX_CODE_ROOT}"
STATE_ROOT="${TWINBOX_CANONICAL_ROOT}"

source "${CODE_ROOT}/scripts/llm_common.sh"
init_llm_backend "${STATE_ROOT}/.env"

PHASE4_DIR="${STATE_ROOT}/runtime/validation/phase-4"
CONTEXT=$(cat "${PHASE4_DIR}/context-pack.json")

PROMPT='You are an enterprise email assistant producing a weekly brief. Produce a JSON object:

{
  "weekly_brief": {
    "period":"<date range>",
    "total_threads_in_window":<number>,
    "flow_summary":[{"flow":"<id>","name":"<name>","count":<n>,"highlight":"<Chinese>"}],
    "top_actions":["<Chinese action 1>","<Chinese action 2>","<Chinese action 3>"],
    "rhythm_observation":"<one paragraph in Chinese about work rhythm>"
  }
}

Rules:
1. Summarize the entire lookback window, not just today
2. Use lifecycle flows to group threads
3. top_actions: the 3 most important things to do this week
4. rhythm_observation: patterns in email activity timing/volume
5. Output ONLY JSON.

Mailbox data:
'"${CONTEXT}"

RAW=$(call_llm "${PROMPT}" 2048)
echo "${RAW}" | clean_json > "${PHASE4_DIR}/weekly-brief-raw.json"
echo "weekly-brief done: ${PHASE4_DIR}/weekly-brief-raw.json"
