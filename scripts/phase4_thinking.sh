#!/usr/bin/env bash
# Phase 4 Thinking: LLM-based daily value outputs
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE4_DIR="${ROOT_DIR}/runtime/validation/phase-4"
DOC_DIR="${ROOT_DIR}/docs/validation"
CONTEXT_PACK="${PHASE4_DIR}/context-pack.json"
source "${ROOT_DIR}/scripts/llm_common.sh"

DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) echo "Usage: bash scripts/phase4_thinking.sh [--dry-run]"; exit 0 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

mkdir -p "${PHASE4_DIR}" "${DOC_DIR}"

if [[ ! -f "${CONTEXT_PACK}" ]]; then
  echo "Missing: ${CONTEXT_PACK}"
  echo "Run: bash scripts/phase4_loading.sh first"
  exit 1
fi

init_llm_backend "${ROOT_DIR}/.env" || exit 1

CONTEXT_CONTENT=$(cat "${CONTEXT_PACK}")

VALUE_PROMPT='You are an enterprise email assistant producing daily actionable outputs for a mailbox owner. Based on the thread data, lifecycle model, and persona below, generate value outputs.

## Your task

Produce a JSON object with this structure:
{
  "daily_urgent": [
    {
      "thread_key": "<thread key>",
      "flow": "<lifecycle flow id or UNMODELED>",
      "stage": "<lifecycle stage id>",
      "urgency_score": <0-100>,
      "why": "<one sentence in Chinese explaining urgency>",
      "action_hint": "<concrete next action in Chinese>",
      "owner": "<who should act>",
      "waiting_on": "<who/what is being waited on>",
      "evidence_source": "<mail_evidence | user_declared_rule>"
    }
  ],
  "pending_replies": [
    {
      "thread_key": "<thread key>",
      "flow": "<flow id>",
      "waiting_on_me": true,
      "why": "<why I need to reply, in Chinese>",
      "suggested_action": "<what to do, in Chinese>",
      "evidence_source": "<mail_evidence | user_declared_rule>"
    }
  ],
  "sla_risks": [
    {
      "thread_key": "<thread key>",
      "flow": "<flow id>",
      "risk_type": "<stalled | overdue | no_response | deployment_failure>",
      "risk_description": "<in Chinese>",
      "days_since_last_activity": <number>,
      "suggested_action": "<in Chinese>"
    }
  ],
  "weekly_brief": {
    "period": "<date range>",
    "total_threads_in_window": <number>,
    "flow_summary": [
      {"flow": "<flow id>", "name": "<flow name>", "count": <number>, "highlight": "<key observation in Chinese>"}
    ],
    "top_actions": ["<top 3 actions for this week, in Chinese>"],
    "rhythm_observation": "<one paragraph in Chinese about work rhythm>"
  }
}

## Rules
1. daily_urgent: rank by urgency_score desc. Include threads where action is needed TODAY.
2. pending_replies: only threads where the mailbox owner needs to respond or approve.
3. sla_risks: threads that are stalled, overdue, or have deployment failures.
4. weekly_brief: summarize the lookback window, not just today.
5. Use lifecycle_flow and lifecycle_stage from the thread data to inform your assessment.
6. If human_context is provided:
   - manual_facts override owner/waiting_on guesses
   - manual_habits inject periodic tasks into daily_urgent or weekly_brief
   - Mark evidence_source accordingly
7. Do NOT invent threads not in the input. Every thread_key must come from the data.
8. Output ONLY the JSON object. No markdown, no explanation.

## Mailbox data:
'"${CONTEXT_CONTENT}"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "=== PROMPT length: $(echo "${VALUE_PROMPT}" | wc -c) chars ==="
  echo "=== DRY RUN ==="
  exit 0
fi

echo "Calling LLM for daily value outputs..."
RAW_RESPONSE=$(call_llm "${VALUE_PROMPT}" "${LLM_MAX_TOKENS:-8192}")
echo "${RAW_RESPONSE}" | clean_json > "${PHASE4_DIR}/llm-response.json"

echo "LLM response saved."

# --- Generate outputs ---
echo "Generating Phase 4 outputs..."

node - <<'NODE' "${PHASE4_DIR}" "${DOC_DIR}"
const fs = require('fs');
const [phase4Dir, docDir] = process.argv.slice(2);
const model = process.env.LLM_MODEL || 'unknown';

const llm = JSON.parse(fs.readFileSync(phase4Dir + '/llm-response.json', 'utf8'));
const urgent = llm.daily_urgent || [];
const pending = llm.pending_replies || [];
const risks = llm.sla_risks || [];
const brief = llm.weekly_brief || {};

// --- daily-urgent.yaml ---
const urgentYaml = [
  'generated_at: "' + new Date().toLocaleString('sv-SE', {timeZone:'Asia/Shanghai'}).replace(' ','T') + '+08:00' + '"',
  'method: "llm"',
  'model: "' + model + '"',
  'daily_urgent:',
];
for (const u of urgent) {
  urgentYaml.push('  - thread_key: ' + JSON.stringify(u.thread_key || ''));
  urgentYaml.push('    flow: ' + (u.flow || 'UNMODELED'));
  urgentYaml.push('    stage: ' + (u.stage || 'unknown'));
  urgentYaml.push('    urgency_score: ' + (u.urgency_score || 0));
  urgentYaml.push('    why: ' + JSON.stringify(u.why || ''));
  urgentYaml.push('    action_hint: ' + JSON.stringify(u.action_hint || ''));
  urgentYaml.push('    owner: ' + JSON.stringify(u.owner || ''));
  urgentYaml.push('    waiting_on: ' + JSON.stringify(u.waiting_on || ''));
  urgentYaml.push('    evidence_source: ' + (u.evidence_source || 'mail_evidence'));
}
fs.writeFileSync(phase4Dir + '/daily-urgent.yaml', urgentYaml.join('\n') + '\n');

// --- pending-replies.yaml ---
const pendingYaml = [
  'generated_at: "' + new Date().toLocaleString('sv-SE', {timeZone:'Asia/Shanghai'}).replace(' ','T') + '+08:00' + '"',
  'method: "llm"',
  'model: "' + model + '"',
  'pending_replies:',
];
for (const p of pending) {
  pendingYaml.push('  - thread_key: ' + JSON.stringify(p.thread_key || ''));
  pendingYaml.push('    flow: ' + (p.flow || 'UNMODELED'));
  pendingYaml.push('    waiting_on_me: ' + (p.waiting_on_me ? 'true' : 'false'));
  pendingYaml.push('    why: ' + JSON.stringify(p.why || ''));
  pendingYaml.push('    suggested_action: ' + JSON.stringify(p.suggested_action || ''));
  pendingYaml.push('    evidence_source: ' + (p.evidence_source || 'mail_evidence'));
}
fs.writeFileSync(phase4Dir + '/pending-replies.yaml', pendingYaml.join('\n') + '\n');

// --- sla-risks.yaml ---
const riskYaml = [
  'generated_at: "' + new Date().toLocaleString('sv-SE', {timeZone:'Asia/Shanghai'}).replace(' ','T') + '+08:00' + '"',
  'method: "llm"',
  'model: "' + model + '"',
  'sla_risks:',
];
for (const r of risks) {
  riskYaml.push('  - thread_key: ' + JSON.stringify(r.thread_key || ''));
  riskYaml.push('    flow: ' + (r.flow || 'UNMODELED'));
  riskYaml.push('    risk_type: ' + (r.risk_type || 'unknown'));
  riskYaml.push('    risk_description: ' + JSON.stringify(r.risk_description || ''));
  riskYaml.push('    days_since_last_activity: ' + (r.days_since_last_activity || 0));
  riskYaml.push('    suggested_action: ' + JSON.stringify(r.suggested_action || ''));
}
fs.writeFileSync(phase4Dir + '/sla-risks.yaml', riskYaml.join('\n') + '\n');

// --- weekly-brief.md ---
const briefLines = [
  '# Weekly Brief',
  '',
  'Generated: ' + new Date().toISOString(),
  'Model: ' + model,
  'Period: ' + (brief.period || 'N/A'),
  '',
  '## Overview',
  '',
  'Total threads in window: ' + (brief.total_threads_in_window || 0),
  '',
];
if (brief.flow_summary) {
  briefLines.push('## Flow Summary');
  briefLines.push('');
  briefLines.push('| Flow | Name | Count | Highlight |');
  briefLines.push('|------|------|-------|-----------|');
  for (const f of brief.flow_summary) {
    briefLines.push('| ' + (f.flow||'') + ' | ' + (f.name||'') + ' | ' + (f.count||0) + ' | ' + (f.highlight||'') + ' |');
  }
  briefLines.push('');
}
if (brief.top_actions) {
  briefLines.push('## Top Actions');
  briefLines.push('');
  for (const a of brief.top_actions) briefLines.push('- ' + a);
  briefLines.push('');
}
if (brief.rhythm_observation) {
  briefLines.push('## Rhythm Observation');
  briefLines.push('');
  briefLines.push(brief.rhythm_observation);
  briefLines.push('');
}
fs.writeFileSync(phase4Dir + '/weekly-brief.md', briefLines.join('\n') + '\n');

// --- Report ---
const report = [
  '# Phase 4 Report: Daily Value Outputs',
  '',
  '## Method',
  '- Inference engine: LLM (' + model + ')',
  '- Input: Phase 1 envelopes + Phase 3 lifecycle model + recent thread bodies',
  '',
  '## Daily Urgent (' + urgent.length + ' items)',
  '',
  '| Thread | Flow | Urgency | Action |',
  '|--------|------|---------|--------|',
];
for (const u of urgent.slice(0, 10)) {
  report.push('| ' + (u.thread_key||'').slice(0,30) + ' | ' + (u.flow||'') + ' | ' + (u.urgency_score||0) + ' | ' + (u.action_hint||'').slice(0,40) + ' |');
}
report.push('');
report.push('## Pending Replies (' + pending.length + ' items)');
report.push('');
for (const p of pending.slice(0, 5)) {
  report.push('- ' + (p.thread_key||'').slice(0,40) + ': ' + (p.why||''));
}
report.push('');
report.push('## SLA Risks (' + risks.length + ' items)');
report.push('');
for (const r of risks.slice(0, 5)) {
  report.push('- [' + (r.risk_type||'') + '] ' + (r.thread_key||'').slice(0,30) + ': ' + (r.risk_description||''));
}
report.push('');
report.push('## Outputs');
report.push('- runtime/validation/phase-4/daily-urgent.yaml');
report.push('- runtime/validation/phase-4/pending-replies.yaml');
report.push('- runtime/validation/phase-4/sla-risks.yaml');
report.push('- runtime/validation/phase-4/weekly-brief.md');

fs.writeFileSync(docDir + '/phase-4-report.md', report.join('\n') + '\n');
console.log('Phase 4 outputs generated: ' + urgent.length + ' urgent, ' + pending.length + ' pending, ' + risks.length + ' risks');
NODE

echo ""
echo "Phase 4 thinking complete."
echo "Outputs:"
echo "  ${PHASE4_DIR}/daily-urgent.yaml"
echo "  ${PHASE4_DIR}/pending-replies.yaml"
echo "  ${PHASE4_DIR}/sla-risks.yaml"
echo "  ${PHASE4_DIR}/weekly-brief.md"
echo "  ${DOC_DIR}/phase-4-report.md"
