#!/usr/bin/env bash
# Phase 2 Loading: read Phase 1 outputs + prepare context for LLM persona inference
# Deterministic, no LLM.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

STATE_ROOT="${TWINBOX_CANONICAL_ROOT}"
PHASE1_DIR="${STATE_ROOT}/runtime/validation/phase-1"
PHASE2_DIR="${STATE_ROOT}/runtime/validation/phase-2"
DOC_DIR="${STATE_ROOT}/docs/validation"
DIAGRAM_DIR="${DOC_DIR}/diagrams"

CENSUS="${PHASE1_DIR}/mailbox-census.json"
INTENT_DIST="${PHASE1_DIR}/intent-distribution.yaml"
CONTACT_DIST="${PHASE1_DIR}/contact-distribution.json"
BODIES="${PHASE1_DIR}/raw/sample-bodies.json"
ENVELOPES="${PHASE1_DIR}/raw/envelopes-merged.json"
INTENT_RESULTS_DIR="${PHASE1_DIR}/intent-results"
PHASE1_CONTEXT="${STATE_ROOT}/runtime/context/phase1-context.json"
INTENT_CLASSIFICATION="${PHASE1_DIR}/intent-classification.json"

# Human context files (optional — skip gracefully if missing)
MANUAL_FACTS="${STATE_ROOT}/runtime/context/manual-facts.yaml"
MANUAL_HABITS="${STATE_ROOT}/runtime/context/manual-habits.yaml"
CALIBRATION="${STATE_ROOT}/runtime/context/instance-calibration-notes.md"

mkdir -p "${PHASE2_DIR}" "${DOC_DIR}" "${DIAGRAM_DIR}"

if [[ ! -f "${PHASE1_CONTEXT}" || ! -f "${INTENT_CLASSIFICATION}" ]]; then
  echo "Missing Phase 1 outputs."
  echo "Run Phase 1 first: bash scripts/phase1_loading.sh && bash scripts/phase1_thinking.sh"
  exit 1
fi

# Build a compact context pack for the thinking layer
node - <<'NODE' "${CENSUS}" "${CONTACT_DIST}" "${BODIES}" "${ENVELOPES}" "${INTENT_RESULTS_DIR}" "${PHASE2_DIR}" "${MANUAL_FACTS}" "${MANUAL_HABITS}" "${CALIBRATION}" "${PHASE1_CONTEXT}" "${INTENT_CLASSIFICATION}"
const fs = require('fs');
const path = require('path');
const [censusPath, contactPath, bodiesPath, envelopesPath, intentDir, phase2Dir, factsPath, habitsPath, calibrationPath, phase1ContextPath, intentClassificationPath] = process.argv.slice(2);

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

function topN(obj, n = 10) {
  return Object.entries(obj)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([key, count]) => ({ key, count }));
}

function normThread(subject) {
  return String(subject || '').toLowerCase()
    .replace(/^(\s*(re|fw|fwd|回复|转发|答复)\s*[:：])+\s*/gi, '')
    .replace(/\s+/g, ' ')
    .trim() || '(no-subject)';
}

function extractTokens(text) {
  const stopWords = new Set(['re', 'fw', 'fwd', '回复', '转发', '关于', '通知', '请', '公司', 'the', 'and', 'for', 'with', 'to', 'of', 'in']);
  return (String(text || '').match(/[A-Za-z0-9\u4e00-\u9fff]{2,}/g) || [])
    .map((token) => token.toLowerCase())
    .filter((token) => !stopWords.has(token));
}

function senderAddr(env) {
  return String(env.from?.addr || env.from_addr || '').toLowerCase();
}

function senderName(env) {
  return String(env.from?.name || env.from_name || '').trim();
}

function senderDomain(env) {
  const addr = senderAddr(env);
  const index = addr.lastIndexOf('@');
  return index >= 0 ? addr.slice(index + 1) : 'unknown';
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

function deriveLegacyArtifacts(envelopes, intents, ownerDomain, foldersScanned, lookbackDays) {
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
    const sender = senderAddr(env) || senderName(env) || 'unknown';
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
    census: {
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
    },
    contacts: {
      top_contacts: topN(bySender, 30),
      top_domains: topN(byDomain, 30),
    },
  };
}

let census;
let contacts;
let bodies;
let envelopes;
let intents = [];

if (fs.existsSync(censusPath) && fs.existsSync(bodiesPath) && fs.existsSync(envelopesPath)) {
  census = JSON.parse(fs.readFileSync(censusPath, 'utf8'));
  contacts = fs.existsSync(contactPath) ? JSON.parse(fs.readFileSync(contactPath, 'utf8')) : {};
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

  const derived = deriveLegacyArtifacts(
    envelopes,
    intents,
    String(phase1Context.owner_domain || '').toLowerCase(),
    phase1Context.stats?.folders_scanned || [],
    phase1Context.lookback_days || null
  );
  census = derived.census;
  contacts = derived.contacts;
}

const envMap = new Map(envelopes.map((env) => [String(env.id), env]));
const intentMapByIdx = new Map(intents.map((intent) => [intent.idx, intent]));
const intentMapById = new Map(
  intents
    .filter((intent) => intent.id !== undefined && intent.id !== null)
    .map((intent) => [String(intent.id), intent])
);

// Build enriched body samples with intent labels
const enriched = bodies.map((b, idx) => {
  const env = envMap.get(String(b.id)) || {};
  const intent = intentMapById.get(String(b.id)) || intentMapByIdx.get(idx) || {};
  return {
    id: b.id,
    subject: env.subject || b.subject || '',
    from: senderAddr(env),
    from_name: senderName(env),
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
const internalExternal = census.distributions.internal_external || census.distributions.byInternalExternal || { internal: 0, external: 0, unknown: 0 };

const context = {
  mailbox_summary: {
    total_envelopes: census.scope.total_envelopes,
    folders: census.scope.folders_scanned,
    internal_external: internalExternal,
    attachment_ratio: census.metrics.attachment_ratio || 0,
  },
  intent_distribution: census.top.intents || [],
  top_domains: census.top.domains || [],
  top_contacts: (contacts.top_contacts || census.top.contacts || []).slice(0, 15),
  top_keywords: (census.top.keywords || []).slice(0, 15),
  high_frequency_threads: (census.threads.high_frequency || []).slice(0, 10),
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
