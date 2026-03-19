#!/usr/bin/env bash
# Phase 2 Thinking: LLM-based persona + business profile inference
# Reads Phase 1 outputs + context pack, calls LLM for real inference.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE2_DIR="${ROOT_DIR}/runtime/validation/phase-2"
DOC_DIR="${ROOT_DIR}/docs/validation"
DIAGRAM_DIR="${DOC_DIR}/diagrams"
CONTEXT_PACK="${PHASE2_DIR}/context-pack.json"
source "${ROOT_DIR}/scripts/llm_common.sh"

DRY_RUN=false
usage() {
  cat <<'USAGE'
Usage:
  bash scripts/phase2_thinking.sh [options]

Options:
  --dry-run    Print prompt without calling LLM
  -h, --help   Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

mkdir -p "${PHASE2_DIR}" "${DOC_DIR}" "${DIAGRAM_DIR}"

if [[ ! -f "${CONTEXT_PACK}" ]]; then
  echo "Missing: ${CONTEXT_PACK}"
  echo "Run: bash scripts/phase2_loading.sh first"
  exit 1
fi

init_llm_backend "${ROOT_DIR}/.env" || exit 1

# --- Build prompt ---
CONTEXT_CONTENT=$(cat "${CONTEXT_PACK}")

PERSONA_PROMPT='You are an enterprise email analyst. Based on the mailbox statistics and email samples below, infer the mailbox owner'\''s profile and their company'\''s business profile.

## Your task

Produce a JSON object with exactly this structure:
{
  "persona_hypotheses": [
    {
      "id": "P1",
      "type": "<role | responsibility | collaboration_pattern | communication_style>",
      "hypothesis": "<one sentence in Chinese>",
      "confidence": <0.0-1.0>,
      "evidence": ["<specific data point from the input>", "..."]
    }
  ],
  "business_hypotheses": [
    {
      "id": "B1",
      "hypothesis": "<one sentence in Chinese>",
      "confidence": <0.0-1.0>,
      "evidence": ["<specific data point>", "..."],
      "ai_entry_points": ["<where AI can add value, in Chinese>", "..."]
    }
  ],
  "confirmation_questions": [
    "<question in Chinese, max 7>"
  ]
}

## Rules
1. Generate 3-5 persona hypotheses and 2-4 business hypotheses
2. Confidence must reflect actual certainty — do NOT default to 0.85+
3. Every evidence item must reference a concrete number, sender, thread, or intent from the input
4. Do not invent data not present in the input
5. confirmation_questions: max 7, each should resolve one ambiguity
6. If human_context is provided in the input, use it to refine your hypotheses:
   - Human-provided facts OVERRIDE email-only inference when they conflict
   - Mark evidence source: "mail_evidence" for email data, "user_declared_rule" or "user_confirmed_fact" for human context
   - If human context contradicts email evidence, flag the conflict in the evidence array
   - Periodic tasks from manual_habits should appear in relevant hypotheses
7. Output ONLY the JSON object. No markdown fences, no explanation.

## Mailbox data:
'"${CONTEXT_CONTENT}"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "=== PROMPT (first 200 lines) ==="
  echo "${PERSONA_PROMPT}" | head -200
  echo "..."
  echo "=== DRY RUN, no LLM call ==="
  exit 0
fi

echo "Calling LLM for persona + business inference..."
RAW_RESPONSE=$(call_llm "${PERSONA_PROMPT}" "${LLM_MAX_TOKENS:-4096}")
echo "${RAW_RESPONSE}" | clean_json > "${PHASE2_DIR}/llm-response.json"

echo "LLM response saved."

# --- Generate outputs ---
echo "Generating Phase 2 outputs..."

node - <<'NODE' "${PHASE2_DIR}" "${DOC_DIR}" "${DIAGRAM_DIR}" "${CONTEXT_PACK}"
const fs = require('fs');
const [phase2Dir, docDir, diagramDir, contextPath] = process.argv.slice(2);

const llm = JSON.parse(fs.readFileSync(`${phase2Dir}/llm-response.json`, 'utf8'));
const context = JSON.parse(fs.readFileSync(contextPath, 'utf8'));
const model = process.env.LLM_MODEL || 'unknown';

const persona = llm.persona_hypotheses || [];
const business = llm.business_hypotheses || [];
const questions = llm.confirmation_questions || [];

// --- persona-hypotheses.yaml ---
const personaYaml = [
  `generated_at: "${new Date().toLocaleString('sv-SE', {timeZone:'Asia/Shanghai'}).replace(' ','T') + '+08:00'}"`,
  `method: "llm"`,
  `model: "${model}"`,
  'persona_hypotheses:',
];
for (const p of persona) {
  personaYaml.push(`  - id: ${p.id}`);
  personaYaml.push(`    type: ${p.type || 'unknown'}`);
  personaYaml.push(`    confidence: ${Number(p.confidence || 0).toFixed(2)}`);
  personaYaml.push(`    hypothesis: ${JSON.stringify(p.hypothesis || '')}`);
  personaYaml.push('    evidence:');
  for (const e of (p.evidence || [])) personaYaml.push(`      - ${JSON.stringify(String(e))}`);
}
fs.writeFileSync(`${phase2Dir}/persona-hypotheses.yaml`, personaYaml.join('\n') + '\n');

// --- business-hypotheses.yaml ---
const businessYaml = [
  `generated_at: "${new Date().toLocaleString('sv-SE', {timeZone:'Asia/Shanghai'}).replace(' ','T') + '+08:00'}"`,
  `method: "llm"`,
  `model: "${model}"`,
  'business_hypotheses:',
];
for (const b of business) {
  businessYaml.push(`  - id: ${b.id}`);
  businessYaml.push(`    confidence: ${Number(b.confidence || 0).toFixed(2)}`);
  businessYaml.push(`    hypothesis: ${JSON.stringify(b.hypothesis || '')}`);
  businessYaml.push('    evidence:');
  for (const e of (b.evidence || [])) businessYaml.push(`      - ${JSON.stringify(String(e))}`);
  businessYaml.push('    ai_entry_points:');
  for (const a of (b.ai_entry_points || [])) businessYaml.push(`      - ${JSON.stringify(String(a))}`);
}
fs.writeFileSync(`${phase2Dir}/business-hypotheses.yaml`, businessYaml.join('\n') + '\n');

// --- relationship map diagram ---
const contacts = context.top_contacts || [];
const domains = context.top_domains || [];
const mmd = ['graph TD', '  User["Mailbox Owner"]'];
for (const c of contacts.slice(0, 8)) {
  const safe = c.key.replace(/[^a-zA-Z0-9]/g, '_');
  mmd.push(`  C_${safe}["${c.key}"]`);
  mmd.push(`  User ---|${c.count}| C_${safe}`);
}
for (const d of domains.slice(0, 3)) {
  const safe = d.key.replace(/[^a-zA-Z0-9]/g, '_');
  mmd.push(`  D_${safe}["${d.key}"]`);
  mmd.push(`  User --> D_${safe}`);
}
fs.writeFileSync(`${diagramDir}/phase-2-relationship-map.mmd`, mmd.join('\n') + '\n');

// --- report ---
const ie = context.mailbox_summary.internal_external;
const total = context.mailbox_summary.total_envelopes;
const intentStr = (context.intent_distribution || []).map(function(i) { return i.key + '(' + i.count + ')'; }).join(', ');
const contactStr = contacts.slice(0,5).map(function(c) { return c.key + '(' + c.count + ')'; }).join(', ');
const domainStr = domains.slice(0,3).map(function(d) { return d.key + '(' + d.count + ')'; }).join(', ');

const reportLines = [
  '# Phase 2 Report: Persona and Business Profile Inference',
  '',
  '## Method',
  '- Inference engine: LLM (' + model + ')',
  '- Input: Phase 1 census + LLM intent results + 30 enriched body samples',
  '- Total envelopes in scope: ' + total,
  '',
  '## Evidence Base',
  '- Internal vs external: internal=' + ie.internal + ', external=' + ie.external + ', unknown=' + ie.unknown,
  '- Top intents (LLM): ' + intentStr,
  '- Top contacts: ' + contactStr,
  '- Top domains: ' + domainStr,
  '',
  '## Persona Hypotheses',
  '',
];
for (const p of persona) {
  reportLines.push('### [' + p.id + '] ' + (p.type || 'unknown') + ' (confidence=' + Number(p.confidence||0).toFixed(2) + ')');
  reportLines.push('');
  reportLines.push(p.hypothesis || '');
  reportLines.push('');
  reportLines.push('Evidence:');
  for (const e of (p.evidence || [])) reportLines.push('- ' + e);
  reportLines.push('');
}
reportLines.push('## Business Hypotheses');
reportLines.push('');
for (const b of business) {
  reportLines.push('### [' + b.id + '] (confidence=' + Number(b.confidence||0).toFixed(2) + ')');
  reportLines.push('');
  reportLines.push(b.hypothesis || '');
  reportLines.push('');
  reportLines.push('Evidence:');
  for (const e of (b.evidence || [])) reportLines.push('- ' + e);
  reportLines.push('');
  reportLines.push('AI entry points:');
  for (const a of (b.ai_entry_points || [])) reportLines.push('- ' + a);
  reportLines.push('');
}
reportLines.push('## Confirmation Questions (max 7)');
reportLines.push('');
questions.forEach(function(q, i) { reportLines.push((i + 1) + '. ' + q); });
reportLines.push('');
reportLines.push('## Outputs');
reportLines.push('- runtime/validation/phase-2/persona-hypotheses.yaml');
reportLines.push('- runtime/validation/phase-2/business-hypotheses.yaml');
reportLines.push('- runtime/validation/phase-2/llm-response.json');
reportLines.push('- docs/validation/phase-2-report.md');
reportLines.push('- docs/validation/diagrams/phase-2-relationship-map.mmd');

fs.writeFileSync(docDir + '/phase-2-report.md', reportLines.join('\n') + '\n');
console.log('Phase 2 outputs generated.');
NODE

echo ""
echo "Phase 2 thinking complete."
echo "Outputs:"
echo "  ${PHASE2_DIR}/persona-hypotheses.yaml"
echo "  ${PHASE2_DIR}/business-hypotheses.yaml"
echo "  ${PHASE2_DIR}/llm-response.json"
echo "  ${DOC_DIR}/phase-2-report.md"
echo "  ${DIAGRAM_DIR}/phase-2-relationship-map.mmd"
