#!/usr/bin/env bash
# Phase 4 子任务: sla-risks (可并行)
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/scripts/llm_common.sh"
init_llm_backend "${ROOT_DIR}/.env"

PHASE4_DIR="${ROOT_DIR}/runtime/validation/phase-4"
CONTEXT=$(cat "${PHASE4_DIR}/context-pack.json")

PROMPT='You are an enterprise email assistant scanning for SLA risks. Produce a JSON object:

{
  "sla_risks": [
    {"thread_key":"<key>","flow":"<flow>","risk_type":"stalled|overdue|no_response|deployment_failure","risk_description":"<Chinese>","days_since_last_activity":<number>,"suggested_action":"<Chinese>"}
  ]
}

Rules:
1. Include threads that are stalled, overdue, or have deployment failures
2. Use lifecycle_flow/stage from thread data to assess risk
3. Every thread_key must come from input data. Output ONLY JSON.

Mailbox data:
'"${CONTEXT}"

RAW=$(call_llm "${PROMPT}" 2048)
echo "${RAW}" | clean_json > "${PHASE4_DIR}/sla-risks-raw.json"
echo "sla-risks done: ${PHASE4_DIR}/sla-risks-raw.json"
