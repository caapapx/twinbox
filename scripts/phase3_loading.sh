#!/usr/bin/env bash
# Phase 3 Loading: prepare context for lifecycle modeling
# Reads Phase 1/2 outputs + human context, builds context pack.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE1_DIR="${ROOT_DIR}/runtime/validation/phase-1"
PHASE2_DIR="${ROOT_DIR}/runtime/validation/phase-2"
PHASE3_DIR="${ROOT_DIR}/runtime/validation/phase-3"
DOC_DIR="${ROOT_DIR}/docs/validation"
DIAGRAM_DIR="${DOC_DIR}/diagrams"

CENSUS="${PHASE1_DIR}/mailbox-census.json"
BODIES="${PHASE1_DIR}/raw/sample-bodies.json"
ENVELOPES="${PHASE1_DIR}/raw/envelopes-merged.json"
INTENT_RESULTS_DIR="${PHASE1_DIR}/intent-results"
PERSONA="${PHASE2_DIR}/persona-hypotheses.yaml"
BUSINESS="${PHASE2_DIR}/business-hypotheses.yaml"

MANUAL_FACTS="${ROOT_DIR}/runtime/context/manual-facts.yaml"
MANUAL_HABITS="${ROOT_DIR}/runtime/context/manual-habits.yaml"
CALIBRATION="${ROOT_DIR}/docs/validation/instance-calibration-notes.md"

mkdir -p "${PHASE3_DIR}" "${DOC_DIR}" "${DIAGRAM_DIR}"

for required in "${CENSUS}" "${BODIES}" "${ENVELOPES}"; do
  if [[ ! -f "${required}" ]]; then
    echo "Missing: ${required}"
    echo "Run Phase 1+2 first."
    exit 1
  fi
done

node - <<'NODE' "${CENSUS}" "${BODIES}" "${ENVELOPES}" "${INTENT_RESULTS_DIR}" "${PERSONA}" "${BUSINESS}" "${PHASE3_DIR}" "${MANUAL_FACTS}" "${MANUAL_HABITS}" "${CALIBRATION}"
const fs = require('fs');
const path = require('path');
const [censusPath, bodiesPath, envelopesPath, intentDir, personaPath, businessPath, phase3Dir, factsPath, habitsPath, calibrationPath] = process.argv.slice(2);

function readIfExists(p) {
  try { return fs.readFileSync(p, 'utf8').trim(); } catch { return ''; }
}

const census = JSON.parse(fs.readFileSync(censusPath, 'utf8'));
const bodies = JSON.parse(fs.readFileSync(bodiesPath, 'utf8'));
const envelopes = JSON.parse(fs.readFileSync(envelopesPath, 'utf8'));
const envMap = new Map(envelopes.map(e => [String(e.id), e]));

// Merge intent results
const intents = [];
if (fs.existsSync(intentDir)) {
  for (const f of fs.readdirSync(intentDir).filter(f => f.endsWith('.json')).sort()) {
    intents.push(...JSON.parse(fs.readFileSync(path.join(intentDir, f), 'utf8')));
  }
}
const intentMap = new Map(intents.map(i => [i.idx, i]));

// Normalize thread key
function normThread(subject) {
  return String(subject || '').toLowerCase()
    .replace(/^(\s*(re|fw|fwd|回复|转发|答复)\s*[:：])+\s*/gi, '')
    .replace(/[-_ ]?(20\d{6}|\d{8})$/, '')
    .replace(/\s+/g, ' ').trim() || '(no-subject)';
}

// Group envelopes by thread
const threads = new Map();
for (const e of envelopes) {
  const key = normThread(e.subject);
  if (!threads.has(key)) threads.set(key, []);
  threads.get(key).push(e);
}
// Sort each thread by date desc
for (const rows of threads.values()) {
  rows.sort((a, b) => new Date(b.date || 0) - new Date(a.date || 0));
}

// Pick top threads by frequency (these are the ones worth modeling)
const threadList = [...threads.entries()]
  .map(([key, rows]) => ({ key, count: rows.length, latest_date: rows[0]?.date || '' }))
  .sort((a, b) => b.count - a.count);

const topThreads = threadList.slice(0, 20);

// Build enriched thread summaries with body excerpts
const threadSummaries = topThreads.map(t => {
  const rows = threads.get(t.key);
  const latest = rows[0];
  const bodyEntry = bodies.find(b => String(b.id) === String(latest.id));
  const intentEntry = intents.find(i => {
    const bodyIdx = bodies.findIndex(b => String(b.id) === String(latest.id));
    return i.idx === bodyIdx;
  });
  return {
    thread_key: t.key,
    count: t.count,
    latest_date: t.latest_date,
    latest_subject: latest.subject || '',
    latest_from: latest.from?.addr || '',
    folder: latest.folder || '',
    intent: intentEntry?.intent || 'unknown',
    intent_confidence: intentEntry?.confidence || 0,
    body_excerpt: bodyEntry ? (bodyEntry.body || '').slice(0, 500) : '',
    participants: [...new Set(rows.map(r => r.from?.addr || '').filter(Boolean))].slice(0, 5),
    date_range: rows.length > 1
      ? (rows[rows.length-1].date || '') + ' ~ ' + (rows[0].date || '')
      : rows[0]?.date || '',
  };
});

// Read Phase 2 outputs
const personaRaw = readIfExists(personaPath);
const businessRaw = readIfExists(businessPath);

// Human context
const factsRaw = readIfExists(factsPath);
const habitsRaw = readIfExists(habitsPath);
const calibrationRaw = readIfExists(calibrationPath);
const hasFacts = factsRaw && factsRaw !== 'facts: []';
const hasHabits = habitsRaw && habitsRaw !== 'habits: []';

const context = {
  mailbox_summary: {
    total_envelopes: census.scope.total_envelopes,
    total_threads: threadList.length,
    folders: census.scope.folders_scanned,
    internal_external: census.distributions.byInternalExternal,
  },
  intent_distribution: census.top.intents,
  persona_summary: personaRaw.slice(0, 1500) || null,
  business_summary: businessRaw.slice(0, 1500) || null,
  top_threads: threadSummaries,
  human_context: {
    has_facts: hasFacts,
    has_habits: hasHabits,
    has_calibration: calibrationRaw.length > 50,
    manual_facts_raw: hasFacts ? factsRaw : null,
    manual_habits_raw: hasHabits ? habitsRaw : null,
    calibration_notes: calibrationRaw.length > 50 ? calibrationRaw.slice(0, 2000) : null,
  },
};

fs.writeFileSync(phase3Dir + '/context-pack.json', JSON.stringify(context, null, 2));
console.log('Context pack: ' + threadSummaries.length + ' top threads, ' + census.scope.total_envelopes + ' total envelopes');
console.log('  human_context: facts=' + (hasFacts ? 'yes' : 'no') + ' habits=' + (hasHabits ? 'yes' : 'no'));
console.log('  -> ' + phase3Dir + '/context-pack.json');
NODE

echo ""
echo "Phase 3 loading complete."
echo "Output: ${PHASE3_DIR}/context-pack.json"
echo ""
echo "Next: bash scripts/phase3_thinking.sh"
