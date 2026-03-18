#!/usr/bin/env bash
# Phase 2 Loading: read Phase 1 outputs + prepare context for LLM persona inference
# Deterministic, no LLM.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE1_DIR="${ROOT_DIR}/runtime/validation/phase-1"
PHASE2_DIR="${ROOT_DIR}/runtime/validation/phase-2"
DOC_DIR="${ROOT_DIR}/docs/validation"
DIAGRAM_DIR="${DOC_DIR}/diagrams"

CENSUS="${PHASE1_DIR}/mailbox-census.json"
INTENT_DIST="${PHASE1_DIR}/intent-distribution.yaml"
CONTACT_DIST="${PHASE1_DIR}/contact-distribution.json"
BODIES="${PHASE1_DIR}/raw/sample-bodies.json"
ENVELOPES="${PHASE1_DIR}/raw/envelopes-merged.json"
INTENT_RESULTS_DIR="${PHASE1_DIR}/intent-results"

# Human context files (optional — skip gracefully if missing)
MANUAL_FACTS="${ROOT_DIR}/runtime/context/manual-facts.yaml"
MANUAL_HABITS="${ROOT_DIR}/runtime/context/manual-habits.yaml"
CALIBRATION="${ROOT_DIR}/docs/validation/instance-calibration-notes.md"

mkdir -p "${PHASE2_DIR}" "${DOC_DIR}" "${DIAGRAM_DIR}"

for required in "${CENSUS}" "${BODIES}" "${ENVELOPES}"; do
  if [[ ! -f "${required}" ]]; then
    echo "Missing: ${required}"
    echo "Run Phase 1 first: bash scripts/phase1_loading.sh && bash scripts/phase1_thinking.sh"
    exit 1
  fi
done

# Build a compact context pack for the thinking layer
node - <<'NODE' "${CENSUS}" "${CONTACT_DIST}" "${BODIES}" "${ENVELOPES}" "${INTENT_RESULTS_DIR}" "${PHASE2_DIR}" "${MANUAL_FACTS}" "${MANUAL_HABITS}" "${CALIBRATION}"
const fs = require('fs');
const path = require('path');
const [censusPath, contactPath, bodiesPath, envelopesPath, intentDir, phase2Dir, factsPath, habitsPath, calibrationPath] = process.argv.slice(2);

function readIfExists(p) {
  try { return fs.readFileSync(p, 'utf8').trim(); } catch { return ''; }
}

function parseYamlSimple(text) {
  // Lightweight: extract items after "facts:" or "habits:" lines
  // Returns array of raw text blocks between "- id:" markers
  if (!text || text === 'facts: []' || text === 'habits: []') return [];
  const items = [];
  const lines = text.split('\n');
  let current = null;
  for (const line of lines) {
    if (/^\s+-\s+id:/.test(line)) {
      if (current) items.push(current);
      current = line.replace(/^\s+-\s+/, '');
    } else if (current && /^\s{4,}\w/.test(line)) {
      current += '\n' + line.trim();
    }
  }
  if (current) items.push(current);
  return items;
}

const census = JSON.parse(fs.readFileSync(censusPath, 'utf8'));
const contacts = fs.existsSync(contactPath) ? JSON.parse(fs.readFileSync(contactPath, 'utf8')) : {};
const bodies = JSON.parse(fs.readFileSync(bodiesPath, 'utf8'));
const envelopes = JSON.parse(fs.readFileSync(envelopesPath, 'utf8'));
const envMap = new Map(envelopes.map(e => [String(e.id), e]));

// Merge LLM intent results
const intents = [];
if (fs.existsSync(intentDir)) {
  for (const f of fs.readdirSync(intentDir).filter(f => f.endsWith('.json')).sort()) {
    intents.push(...JSON.parse(fs.readFileSync(path.join(intentDir, f), 'utf8')));
  }
}
const intentMap = new Map(intents.map(i => [i.idx, i]));

// Build enriched body samples with intent labels
const enriched = bodies.map((b, idx) => {
  const env = envMap.get(String(b.id)) || {};
  const intent = intentMap.get(idx) || {};
  return {
    id: b.id,
    subject: env.subject || b.subject || '',
    from: env.from?.addr || '',
    from_name: env.from?.name || '',
    date: env.date || '',
    folder: env.folder || b.folder || '',
    intent: intent.intent || 'unknown',
    intent_confidence: intent.confidence || 0,
    intent_evidence: intent.evidence || '',
    body_excerpt: (b.body || '').slice(0, 600),
  };
});

// Compact context for LLM
const factsRaw = readIfExists(factsPath);
const habitsRaw = readIfExists(habitsPath);
const calibrationRaw = readIfExists(calibrationPath);

const factsItems = parseYamlSimple(factsRaw);
const habitsItems = parseYamlSimple(habitsRaw);

const context = {
  mailbox_summary: {
    total_envelopes: census.scope.total_envelopes,
    folders: census.scope.folders_scanned,
    internal_external: census.distributions.byInternalExternal,
    attachment_ratio: census.metrics.attachment_ratio,
  },
  intent_distribution: census.top.intents,
  top_domains: census.top.domains,
  top_contacts: (contacts.top_contacts || census.top.contacts || []).slice(0, 15),
  top_keywords: (census.top.keywords || []).slice(0, 15),
  high_frequency_threads: census.threads.high_frequency.slice(0, 10),
  long_threads: (census.threads.long_threads || []).slice(0, 10),
  enriched_samples: enriched,
  human_context: {
    has_facts: factsItems.length > 0,
    has_habits: habitsItems.length > 0,
    has_calibration: calibrationRaw.length > 0,
    manual_facts_raw: factsItems.length > 0 ? factsRaw : null,
    manual_habits_raw: habitsItems.length > 0 ? habitsRaw : null,
    calibration_notes: calibrationRaw.length > 50 ? calibrationRaw.slice(0, 2000) : null,
  },
};

fs.writeFileSync(`${phase2Dir}/context-pack.json`, JSON.stringify(context, null, 2));

console.log('Context pack: ' + enriched.length + ' enriched samples, ' + census.scope.total_envelopes + ' total envelopes');
console.log('  human_context: facts=' + factsItems.length + ' habits=' + habitsItems.length + ' calibration=' + (calibrationRaw.length > 50 ? 'yes' : 'no'));
console.log('  -> ' + phase2Dir + '/context-pack.json');
NODE

echo ""
echo "Phase 2 loading complete."
echo "Output: ${PHASE2_DIR}/context-pack.json"
echo ""
echo "Next: bash scripts/phase2_thinking.sh"
