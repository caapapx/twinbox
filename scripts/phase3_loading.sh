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
PHASE1_CONTEXT="${ROOT_DIR}/runtime/context/phase1-context.json"
INTENT_CLASSIFICATION="${PHASE1_DIR}/intent-classification.json"
PERSONA="${PHASE2_DIR}/persona-hypotheses.yaml"
BUSINESS="${PHASE2_DIR}/business-hypotheses.yaml"

MANUAL_FACTS="${ROOT_DIR}/runtime/context/manual-facts.yaml"
MANUAL_HABITS="${ROOT_DIR}/runtime/context/manual-habits.yaml"
CALIBRATION="${ROOT_DIR}/runtime/context/instance-calibration-notes.md"

mkdir -p "${PHASE3_DIR}" "${DOC_DIR}" "${DIAGRAM_DIR}"

if [[ ! -f "${PHASE1_CONTEXT}" || ! -f "${INTENT_CLASSIFICATION}" ]]; then
  echo "Missing Phase 1 outputs."
  echo "Run Phase 1 first."
  exit 1
fi

node - <<'NODE' "${CENSUS}" "${BODIES}" "${ENVELOPES}" "${INTENT_RESULTS_DIR}" "${PERSONA}" "${BUSINESS}" "${PHASE3_DIR}" "${MANUAL_FACTS}" "${MANUAL_HABITS}" "${CALIBRATION}" "${PHASE1_CONTEXT}" "${INTENT_CLASSIFICATION}"
const fs = require('fs');
const path = require('path');
const [censusPath, bodiesPath, envelopesPath, intentDir, personaPath, businessPath, phase3Dir, factsPath, habitsPath, calibrationPath, phase1ContextPath, intentClassificationPath] = process.argv.slice(2);

function readIfExists(p) {
  try { return fs.readFileSync(p, 'utf8').trim(); } catch { return ''; }
}

function topN(obj, n = 10) {
  return Object.entries(obj)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([key, count]) => ({ key, count }));
}

function senderAddr(env) {
  return String(env.from?.addr || env.from_addr || '').toLowerCase();
}

function senderDomain(env) {
  const addr = senderAddr(env);
  const index = addr.lastIndexOf('@');
  return index >= 0 ? addr.slice(index + 1) : 'unknown';
}

function extractTokens(text) {
  const stopWords = new Set(['re', 'fw', 'fwd', '回复', '转发', '关于', '通知', '请', '公司', 'the', 'and', 'for', 'with', 'to', 'of', 'in']);
  return (String(text || '').match(/[A-Za-z0-9\u4e00-\u9fff]{2,}/g) || [])
    .map((token) => token.toLowerCase())
    .filter((token) => !stopWords.has(token));
}

function normalizeEnvelope(env) {
  return {
    id: String(env.id),
    folder: env.folder || 'INBOX',
    subject: env.subject || '',
    date: env.date || '',
    has_attachment: !!env.has_attachment,
    from: env.from || {
      addr: env.from_addr || '',
      name: env.from_name || '',
    },
  };
}

function deriveLegacyCensus(envelopes, intents, ownerDomain, foldersScanned, lookbackDays) {
  const byDomain = {};
  const bySender = {};
  const byKeyword = {};
  const byIntent = {};
  const byInternalExternal = { internal: 0, external: 0, unknown: 0 };
  const threadCounts = {};
  let withAttachment = 0;

  const intentById = new Map(intents.map((intent) => [String(intent.id), intent]));

  for (const env of envelopes) {
    const domain = senderDomain(env);
    const sender = senderAddr(env) || env.from?.name || 'unknown';
    const intent = intentById.get(String(env.id))?.intent || 'unknown';

    byDomain[domain] = (byDomain[domain] || 0) + 1;
    bySender[sender] = (bySender[sender] || 0) + 1;
    byIntent[intent] = (byIntent[intent] || 0) + 1;
    threadCounts[normThread(env.subject)] = (threadCounts[normThread(env.subject)] || 0) + 1;

    for (const token of extractTokens(env.subject)) {
      byKeyword[token] = (byKeyword[token] || 0) + 1;
    }

    if (env.has_attachment) withAttachment++;

    if (domain === 'unknown') {
      byInternalExternal.unknown += 1;
    } else if (ownerDomain && domain === ownerDomain) {
      byInternalExternal.internal += 1;
    } else {
      byInternalExternal.external += 1;
    }
  }

  const total = envelopes.length;
  const threadsTop = topN(threadCounts, 15);

  return {
    generated_at: new Date().toISOString(),
    scope: {
      folders_scanned: foldersScanned,
      lookback_days: lookbackDays || null,
      total_envelopes: total,
      sampled_bodies: 0,
    },
    distributions: {
      internal_external: byInternalExternal,
    },
    metrics: {
      attachment_ratio: total ? Number((withAttachment / total).toFixed(4)) : 0,
    },
    threads: {
      high_frequency: threadsTop.slice(0, 10),
      long_threads: threadsTop.filter((thread) => thread.count >= 3),
    },
    top: {
      intents: topN(byIntent, 10),
      domains: topN(byDomain, 10),
      contacts: topN(bySender, 15),
      keywords: topN(byKeyword, 15),
    },
  };
}

let census;
let bodies;
let envelopes;
let intents = [];

if (fs.existsSync(censusPath) && fs.existsSync(bodiesPath) && fs.existsSync(envelopesPath)) {
  census = JSON.parse(fs.readFileSync(censusPath, 'utf8'));
  bodies = JSON.parse(fs.readFileSync(bodiesPath, 'utf8'));
  envelopes = JSON.parse(fs.readFileSync(envelopesPath, 'utf8')).map(normalizeEnvelope);

  if (fs.existsSync(intentDir)) {
    for (const f of fs.readdirSync(intentDir).filter((file) => file.endsWith('.json')).sort()) {
      intents.push(...JSON.parse(fs.readFileSync(path.join(intentDir, f), 'utf8')));
    }
  }
} else {
  const phase1Context = JSON.parse(fs.readFileSync(phase1ContextPath, 'utf8'));
  const intentClassification = JSON.parse(fs.readFileSync(intentClassificationPath, 'utf8'));

  envelopes = (phase1Context.envelopes || []).map(normalizeEnvelope);
  const sampledBodies = phase1Context.sampled_bodies || {};
  bodies = Object.entries(sampledBodies).map(([id, row]) => ({
    id,
    folder: envelopes.find((env) => String(env.id) === String(id))?.folder || '',
    subject: row.subject || '',
    body: row.body || '',
  }));
  intents = intentClassification.classifications || [];
  census = deriveLegacyCensus(
    envelopes,
    intents,
    String(phase1Context.owner_domain || '').toLowerCase(),
    phase1Context.stats?.folders_scanned || [],
    phase1Context.lookback_days || null
  );
}

const envMap = new Map(envelopes.map((env) => [String(env.id), env]));
const intentMapByIdx = new Map(intents.map((intent) => [intent.idx, intent]));
const intentMapById = new Map(
  intents
    .filter((intent) => intent.id !== undefined && intent.id !== null)
    .map((intent) => [String(intent.id), intent])
);

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
  const bodyIdx = bodies.findIndex(b => String(b.id) === String(latest.id));
  const intentEntry = intentMapById.get(String(latest.id)) || intentMapByIdx.get(bodyIdx);
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
const internalExternal = census.distributions.internal_external || census.distributions.byInternalExternal || { internal: 0, external: 0, unknown: 0 };

const context = {
  mailbox_summary: {
    total_envelopes: census.scope.total_envelopes,
    total_threads: threadList.length,
    folders: census.scope.folders_scanned,
    internal_external: internalExternal,
  },
  intent_distribution: census.top.intents || [],
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
console.log('  human_context: facts=' + (hasFacts ? 'yes' : 'no') + ' habits=' + (hasHabits ? 'yes' : 'no') + ' calibration=' + (calibrationRaw.length > 50 ? 'yes' : 'no'));
console.log('  -> ' + phase3Dir + '/context-pack.json');
NODE

echo ""
echo "Phase 3 loading complete."
echo "Output: ${PHASE3_DIR}/context-pack.json"
echo ""
echo "Next: bash scripts/phase3_thinking.sh"
