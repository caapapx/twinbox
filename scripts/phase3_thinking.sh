#!/usr/bin/env bash
# Phase 3 Thinking: LLM-based lifecycle modeling
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE3_DIR="${ROOT_DIR}/runtime/validation/phase-3"
DOC_DIR="${ROOT_DIR}/docs/validation"
DIAGRAM_DIR="${DOC_DIR}/diagrams"
CONTEXT_PACK="${PHASE3_DIR}/context-pack.json"

ENV_FILE="${ROOT_DIR}/.env"
if [[ -f "${ENV_FILE}" ]]; then
  set -a; source "${ENV_FILE}"; set +a
fi

DRY_RUN=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help) echo "Usage: bash scripts/phase3_thinking.sh [--dry-run]"; exit 0 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

mkdir -p "${PHASE3_DIR}" "${DOC_DIR}" "${DIAGRAM_DIR}"

if [[ ! -f "${CONTEXT_PACK}" ]]; then
  echo "Missing: ${CONTEXT_PACK}"
  echo "Run: bash scripts/phase3_loading.sh first"
  exit 1
fi

# LLM backend detection (same as phase1/2)
LLM_BACKEND=""
if [[ -n "${LLM_API_KEY:-}" ]]; then
  LLM_BACKEND="openai"
  LLM_URL="${LLM_API_URL:-}"
  LLM_MODEL_NAME="${LLM_MODEL:-}"
  echo "LLM backend: OpenAI-compatible (${LLM_MODEL_NAME})"
elif [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
  LLM_BACKEND="anthropic"
  echo "LLM backend: Anthropic API"
else
  echo "No LLM backend. Set LLM_API_KEY in .env."
  exit 1
fi

CONTEXT_CONTENT=$(cat "${CONTEXT_PACK}")

LIFECYCLE_PROMPT='You are an enterprise email workflow analyst. Based on the mailbox data, persona hypotheses, and thread summaries below, build a thread-level lifecycle model.

## Your task

Produce a JSON object with this structure:
{
  "lifecycle_flows": [
    {
      "id": "LF1",
      "name": "<flow name in Chinese>",
      "description": "<one sentence in Chinese>",
      "evidence_threads": ["<thread_key(count)>", "..."],
      "stages": [
        {
          "id": "LF1-S1",
          "name": "<stage name in Chinese>",
          "entry_signal": "<what triggers entry, in Chinese>",
          "exit_signal": "<what triggers exit>",
          "owner_guess": "<who owns this stage>",
          "waiting_on": "<who/what is being waited on>",
          "due_hint": "<typical deadline pattern>",
          "risk_signal": "<what indicates risk>",
          "ai_action": "<summarize|classify|remind|draft — pick 1-2>"
        }
      ]
    }
  ],
  "thread_stage_samples": [
    {
      "thread_key": "<from top_threads>",
      "flow": "LF1",
      "inferred_stage": "LF1-S3",
      "stage_name": "<stage name>",
      "evidence": "<why this stage, referencing email content>",
      "confidence": 0.82,
      "ai_action": "<recommended action>"
    }
  ],
  "phase4_recommendations": [
    "<which 2 flows are most ready for Phase 4 value output, and why>"
  ],
  "policy_suggestions": [
    "<max 5 suggestions for config/profiles/rules>"
  ]
}

## Rules
1. Identify 3-5 lifecycle flows from the data. Do NOT predefine business types — derive them from evidence.
2. Each flow must have at least 4 stages with entry/exit signals.
3. thread_stage_samples: classify each of the top_threads into a flow+stage. If a thread does not fit any flow, mark flow as "UNMODELED".
4. Every evidence and signal must reference concrete thread_keys, subjects, or patterns from the input.
5. If human_context is provided:
   - Use manual_facts to correct owner_guess and waiting_on
   - Use manual_habits to inject periodic tasks as a separate flow or stage
   - Mark evidence source: "mail_evidence" vs "user_declared_rule"
6. Confidence must reflect actual certainty.
7. Output ONLY the JSON object. No markdown, no explanation.

## Mailbox data:
'"${CONTEXT_CONTENT}"

if [[ "${DRY_RUN}" == "true" ]]; then
  echo "=== PROMPT length: $(echo "${LIFECYCLE_PROMPT}" | wc -c) chars ==="
  echo "=== DRY RUN ==="
  exit 0
fi

# --- Call LLM ---
echo "Calling LLM for lifecycle modeling..."

call_llm() {
  local prompt="$1"
  if [[ "${LLM_BACKEND}" == "openai" ]]; then
    local request_body
    request_body=$(node -e '
      console.log(JSON.stringify({
        model: process.argv[2],
        messages: [{ role: "user", content: process.argv[1] }],
        temperature: 0.2,
        max_tokens: Number(process.env.LLM_MAX_TOKENS || 8192),
      }));
    ' "${prompt}" "${LLM_MODEL_NAME}")

    local raw
    raw=$(curl -s -X POST "${LLM_URL}" \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer ${LLM_API_KEY}" \
      -d "${request_body}" 2>/dev/null)

    echo "${raw}" | node -e '
      const c=[]; process.stdin.on("data",d=>c.push(d));
      process.stdin.on("end",()=>{
        try {
          const r=JSON.parse(Buffer.concat(c).toString("utf8"));
          if(r.error){process.stderr.write("API error: "+JSON.stringify(r.error)+"\n");process.stdout.write("{}");return;}
          process.stdout.write(r.choices?.[0]?.message?.content||"{}");
        } catch(e){process.stderr.write("Parse error\n");process.stdout.write("{}");}
      });
    '
  elif [[ "${LLM_BACKEND}" == "anthropic" ]]; then
    local api_url="${ANTHROPIC_BASE_URL:-https://api.anthropic.com}/v1/messages"
    local model="${ANTHROPIC_MODEL:-claude-sonnet-4-20250514}"
    local request_body
    request_body=$(node -e '
      console.log(JSON.stringify({
        model: process.argv[2], max_tokens: 8192,
        messages: [{ role: "user", content: process.argv[1] }]
      }));
    ' "${prompt}" "${model}")

    local raw
    raw=$(curl -s -X POST "${api_url}" \
      -H "Content-Type: application/json" \
      -H "x-api-key: ${ANTHROPIC_API_KEY}" \
      -H "anthropic-version: 2023-06-01" \
      -d "${request_body}" 2>/dev/null)

    echo "${raw}" | node -e '
      const c=[]; process.stdin.on("data",d=>c.push(d));
      process.stdin.on("end",()=>{
        try {
          const r=JSON.parse(Buffer.concat(c).toString("utf8"));
          if(r.error){process.stderr.write("API error\n");process.stdout.write("{}");return;}
          process.stdout.write((r.content||[]).map(c=>c.text||"").join(""));
        } catch(e){process.stdout.write("{}");}
      });
    '
  fi
}

RAW_RESPONSE=$(call_llm "${LIFECYCLE_PROMPT}")

# Parse response
echo "${RAW_RESPONSE}" | node -e '
  const c=[]; process.stdin.on("data",d=>c.push(d));
  process.stdin.on("end",()=>{
    let t=Buffer.concat(c).toString("utf8").trim();
    t=t.replace(/^```(?:json)?\s*/m,"").replace(/\s*```\s*$/m,"").trim();
    try { process.stdout.write(JSON.stringify(JSON.parse(t),null,2)); }
    catch(e){ process.stderr.write("JSON parse failed: "+e.message+"\n"); process.stdout.write("{}"); }
  });
' > "${PHASE3_DIR}/llm-response.json"

echo "LLM response saved."

# --- Generate outputs ---
echo "Generating Phase 3 outputs..."

node - <<'NODE' "${PHASE3_DIR}" "${DOC_DIR}" "${DIAGRAM_DIR}"
const fs = require('fs');
const [phase3Dir, docDir, diagramDir] = process.argv.slice(2);
const model = process.env.LLM_MODEL || 'unknown';

const llm = JSON.parse(fs.readFileSync(phase3Dir + '/llm-response.json', 'utf8'));
const flows = llm.lifecycle_flows || [];
const samples = llm.thread_stage_samples || [];
const p4recs = llm.phase4_recommendations || [];
const policySugs = llm.policy_suggestions || [];

// --- lifecycle-model.yaml ---
const yaml = [
  'generated_at: "' + new Date().toISOString() + '"',
  'method: "llm"',
  'model: "' + model + '"',
  '',
  'lifecycle_flows:',
];
for (const f of flows) {
  yaml.push('');
  yaml.push('  - id: ' + f.id);
  yaml.push('    name: ' + JSON.stringify(f.name || ''));
  yaml.push('    description: ' + JSON.stringify(f.description || ''));
  yaml.push('    evidence_threads:');
  for (const t of (f.evidence_threads || [])) yaml.push('      - ' + JSON.stringify(t));
  yaml.push('    stages:');
  for (const s of (f.stages || [])) {
    yaml.push('      - id: ' + s.id);
    yaml.push('        name: ' + JSON.stringify(s.name || ''));
    yaml.push('        entry_signal: ' + JSON.stringify(s.entry_signal || ''));
    yaml.push('        exit_signal: ' + JSON.stringify(s.exit_signal || ''));
    yaml.push('        owner_guess: ' + JSON.stringify(s.owner_guess || ''));
    yaml.push('        waiting_on: ' + JSON.stringify(s.waiting_on || ''));
    yaml.push('        due_hint: ' + JSON.stringify(s.due_hint || ''));
    yaml.push('        risk_signal: ' + JSON.stringify(s.risk_signal || ''));
    yaml.push('        ai_action: ' + JSON.stringify(s.ai_action || ''));
  }
}
fs.writeFileSync(phase3Dir + '/lifecycle-model.yaml', yaml.join('\n') + '\n');

// --- thread-stage-samples.json ---
fs.writeFileSync(phase3Dir + '/thread-stage-samples.json', JSON.stringify({ samples: samples }, null, 2));

// --- Mermaid: lifecycle overview ---
const overviewMmd = ['graph TD'];
for (const f of flows) {
  const safe = f.id;
  overviewMmd.push('  ' + safe + '["' + (f.name || f.id) + '"]');
  for (const s of (f.stages || [])) {
    const sid = s.id.replace(/-/g, '_');
    overviewMmd.push('  ' + sid + '["' + (s.name || s.id) + '"]');
  }
  const stages = f.stages || [];
  for (let i = 0; i < stages.length - 1; i++) {
    const a = stages[i].id.replace(/-/g, '_');
    const b = stages[i+1].id.replace(/-/g, '_');
    overviewMmd.push('  ' + a + ' --> ' + b);
  }
}
fs.writeFileSync(diagramDir + '/phase-3-lifecycle-overview.mmd', overviewMmd.join('\n') + '\n');

// --- Mermaid: thread state machine (first flow) ---
if (flows.length > 0) {
  const f = flows[0];
  const smMmd = ['stateDiagram-v2'];
  const stages = f.stages || [];
  if (stages.length > 0) {
    smMmd.push('  [*] --> ' + stages[0].id.replace(/-/g, '_'));
    for (const s of stages) {
      smMmd.push('  ' + s.id.replace(/-/g, '_') + ' : ' + (s.name || s.id));
    }
    for (let i = 0; i < stages.length - 1; i++) {
      const a = stages[i].id.replace(/-/g, '_');
      const b = stages[i+1].id.replace(/-/g, '_');
      smMmd.push('  ' + a + ' --> ' + b);
    }
    smMmd.push('  ' + stages[stages.length-1].id.replace(/-/g, '_') + ' --> [*]');
  }
  fs.writeFileSync(diagramDir + '/phase-3-thread-state-machine.mmd', smMmd.join('\n') + '\n');
}

// --- Report ---
const lines = [
  '# Phase 3 Report: Lifecycle Modeling',
  '',
  '## Method',
  '- Inference engine: LLM (' + model + ')',
  '- Input: Phase 1 census + Phase 2 persona + 20 top threads with body excerpts',
  '',
  '## Lifecycle Flows',
  '',
];
for (const f of flows) {
  lines.push('### ' + f.id + ': ' + (f.name || ''));
  lines.push('');
  lines.push(f.description || '');
  lines.push('');
  lines.push('Evidence threads: ' + (f.evidence_threads || []).join(', '));
  lines.push('');
  lines.push('| Stage | Name | Entry Signal | Risk Signal | AI Action |');
  lines.push('|-------|------|-------------|-------------|-----------|');
  for (const s of (f.stages || [])) {
    lines.push('| ' + s.id + ' | ' + (s.name||'') + ' | ' + (s.entry_signal||'').slice(0,40) + ' | ' + (s.risk_signal||'').slice(0,30) + ' | ' + (s.ai_action||'') + ' |');
  }
  lines.push('');
}

lines.push('## Thread Stage Samples');
lines.push('');
lines.push('| Thread | Flow | Stage | Confidence | Evidence |');
lines.push('|--------|------|-------|------------|----------|');
for (const s of samples.slice(0, 15)) {
  lines.push('| ' + (s.thread_key||'').slice(0,30) + ' | ' + (s.flow||'') + ' | ' + (s.inferred_stage||'') + ' | ' + (s.confidence||0) + ' | ' + (s.evidence||'').slice(0,40) + ' |');
}
lines.push('');

lines.push('## Phase 4 Recommendations');
lines.push('');
for (const r of p4recs) lines.push('- ' + r);
lines.push('');

lines.push('## Policy Suggestions');
lines.push('');
for (const s of policySugs) lines.push('- ' + s);
lines.push('');

lines.push('## Outputs');
lines.push('- runtime/validation/phase-3/lifecycle-model.yaml');
lines.push('- runtime/validation/phase-3/thread-stage-samples.json');
lines.push('- docs/validation/diagrams/phase-3-lifecycle-overview.mmd');
lines.push('- docs/validation/diagrams/phase-3-thread-state-machine.mmd');

fs.writeFileSync(docDir + '/phase-3-report.md', lines.join('\n') + '\n');
console.log('Phase 3 outputs generated.');
NODE

echo ""
echo "Phase 3 thinking complete."
echo "Outputs:"
echo "  ${PHASE3_DIR}/lifecycle-model.yaml"
echo "  ${PHASE3_DIR}/thread-stage-samples.json"
echo "  ${DOC_DIR}/phase-3-report.md"
echo "  ${DIAGRAM_DIR}/phase-3-lifecycle-overview.mmd"
echo "  ${DIAGRAM_DIR}/phase-3-thread-state-machine.mmd"
