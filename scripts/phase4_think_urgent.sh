#!/usr/bin/env bash
# Phase 4 子任务: daily-urgent + pending-replies (可并行)
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/scripts/llm_common.sh"
init_llm_backend "${ROOT_DIR}/.env"

PHASE4_DIR="${ROOT_DIR}/runtime/validation/phase-4"
CONTEXT=$(cat "${PHASE4_DIR}/context-pack.json")

PROMPT='You are an enterprise email assistant. Based on the thread data below, produce a JSON object with exactly two keys:

{
  "daily_urgent": [
    {"thread_key":"<key>","flow":"<flow>","stage":"<stage>","urgency_score":<0-100>,"why":"<Chinese>","action_hint":"<Chinese>","owner":"<who>","waiting_on":"<who>","evidence_source":"mail_evidence|user_declared_rule"}
  ],
  "pending_replies": [
    {"thread_key":"<key>","flow":"<flow>","waiting_on_me":true,"why":"<Chinese>","suggested_action":"<Chinese>","evidence_source":"mail_evidence|user_declared_rule"}
  ]
}

Rules:
1. daily_urgent: threads needing action TODAY, ranked by urgency_score desc
2. pending_replies: only threads where mailbox owner must respond/approve
3. Use lifecycle_flow/stage from thread data
4. If human_context has manual_facts, override owner/waiting_on guesses
5. Every thread_key must come from input data. Output ONLY JSON.

Mailbox data:
'"${CONTEXT}"

RAW=$(call_llm "${PROMPT}" 4096)
echo "${RAW}" | clean_json > "${PHASE4_DIR}/urgent-pending-raw.json"
echo "urgent+pending done: ${PHASE4_DIR}/urgent-pending-raw.json"
