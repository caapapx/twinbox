#!/usr/bin/env bash
# Phase 4 Loading: fetch recent thread bodies + build context for LLM value output
# Deterministic I/O, no LLM.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
CONFIG_FILE="${ROOT_DIR}/runtime/himalaya/config.toml"
PHASE1_DIR="${ROOT_DIR}/runtime/validation/phase-1"
PHASE3_DIR="${ROOT_DIR}/runtime/validation/phase-3"
PHASE4_DIR="${ROOT_DIR}/runtime/validation/phase-4"

ENVELOPES="${PHASE1_DIR}/raw/envelopes-merged.json"
BODIES="${PHASE1_DIR}/raw/sample-bodies.json"
CENSUS="${PHASE1_DIR}/mailbox-census.json"
LIFECYCLE="${PHASE3_DIR}/lifecycle-model.yaml"
THREAD_SAMPLES="${PHASE3_DIR}/thread-stage-samples.json"
PERSONA="${ROOT_DIR}/runtime/validation/phase-2/persona-hypotheses.yaml"

MANUAL_FACTS="${ROOT_DIR}/runtime/context/manual-facts.yaml"
MANUAL_HABITS="${ROOT_DIR}/runtime/context/manual-habits.yaml"
CALIBRATION="${ROOT_DIR}/docs/validation/instance-calibration-notes.md"

LOOKBACK_DAYS=18
MAX_BODY_FETCH=24
ACCOUNT_OVERRIDE=""

usage() {
  cat <<'USAGE'
Usage: bash scripts/phase4_loading.sh [options]
Options:
  --account <name>         Override MAIL_ACCOUNT_NAME
  --lookback-days <n>      Lookback window (default: 18)
  --max-body-fetch <n>     Max bodies to fetch live (default: 24)
  -h, --help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --account) ACCOUNT_OVERRIDE="${2:-}"; shift 2 ;;
    --lookback-days) LOOKBACK_DAYS="${2:-}"; shift 2 ;;
    --max-body-fetch) MAX_BODY_FETCH="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

mkdir -p "${PHASE4_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then echo "Missing .env"; exit 1; fi
set -a; source "${ENV_FILE}"; set +a
bash "${ROOT_DIR}/scripts/check_env.sh"
bash "${ROOT_DIR}/scripts/render_himalaya_config.sh"

if ! command -v himalaya >/dev/null 2>&1; then
  if [[ -x "${ROOT_DIR}/runtime/bin/himalaya" ]]; then
    HIMALAYA_BIN="${ROOT_DIR}/runtime/bin/himalaya"
  else
    echo "himalaya CLI not found"; exit 1
  fi
else
  HIMALAYA_BIN="$(command -v himalaya)"
fi

ACCOUNT="${ACCOUNT_OVERRIDE:-${MAIL_ACCOUNT_NAME}}"

for required in "${ENVELOPES}" "${THREAD_SAMPLES}"; do
  if [[ ! -f "${required}" ]]; then
    echo "Missing: ${required}"; echo "Run Phase 1-3 first."; exit 1
  fi
done

# Build context pack: recent threads + live body fetch + lifecycle model + human context
node - <<'NODE' "${ENVELOPES}" "${BODIES}" "${THREAD_SAMPLES}" "${LIFECYCLE}" "${PERSONA}" "${CENSUS}" "${PHASE4_DIR}" "${HIMALAYA_BIN}" "${CONFIG_FILE}" "${ACCOUNT}" "${MAIL_ADDRESS}" "${LOOKBACK_DAYS}" "${MAX_BODY_FETCH}" "${MANUAL_FACTS}" "${MANUAL_HABITS}" "${CALIBRATION}"
const fs = require('fs');
const cp = require('child_process');
const [envelopesPath, bodiesPath, threadSamplesPath, lifecyclePath, personaPath, censusPath, phase4Dir, himalayaBin, configPath, account, mailAddress, lookbackDaysRaw, maxBodyFetchRaw, factsPath, habitsPath, calibrationPath] = process.argv.slice(2);

function readIfExists(p) {
  try { return fs.readFileSync(p, 'utf8').trim(); } catch { return ''; }
}

const envelopes = JSON.parse(fs.readFileSync(envelopesPath, 'utf8'));
const existingBodies = JSON.parse(fs.readFileSync(bodiesPath, 'utf8'));
const threadSamples = JSON.parse(fs.readFileSync(threadSamplesPath, 'utf8'));
const lifecycleRaw = readIfExists(lifecyclePath);
const personaRaw = readIfExists(personaPath);
const censusRaw = readIfExists(censusPath);
const lookbackDays = Number(lookbackDaysRaw);
const maxBodyFetch = Number(maxBodyFetchRaw);

// Existing body map for cache
const bodyMap = new Map(existingBodies.map(b => [String(b.id), b]));

// Normalize thread key
function normThread(subject) {
  return String(subject || '').toLowerCase()
    .replace(/^(\s*(re|fw|fwd|回复|转发|答复)\s*[:：])+\s*/gi, '')
    .replace(/\s+/g, ' ').trim() || '(no-subject)';
}

// Filter recent envelopes
const now = new Date();
const cutoff = new Date(now.getTime() - lookbackDays * 86400000);
function parseDate(s) {
  if (!s) return null;
  const d = new Date(String(s).replace(' ', 'T'));
  return Number.isNaN(d.getTime()) ? null : d;
}

const recent = envelopes
  .map(e => ({ ...e, dt: parseDate(e.date) }))
  .filter(e => e.dt && e.dt >= cutoff);

// Group by thread
const threads = new Map();
for (const e of recent) {
  const key = normThread(e.subject);
  if (!threads.has(key)) threads.set(key, []);
  threads.get(key).push(e);
}

// Pick threads worth analyzing (multi-message or lifecycle-modeled)
const modeledKeys = new Set((threadSamples.samples || []).map(s => s.thread_key));
const candidates = [...threads.entries()]
  .map(([key, rows]) => ({
    key,
    count: rows.length,
    modeled: modeledKeys.has(key),
    latest: rows.sort((a, b) => new Date(b.date) - new Date(a.date))[0],
  }))
  .sort((a, b) => (b.modeled ? 1 : 0) - (a.modeled ? 1 : 0) || b.count - a.count)
  .slice(0, 30);

// Fetch bodies for candidates (use cache when available)
let fetched = 0;
const threadContexts = [];

for (const c of candidates) {
  const e = c.latest;
  const id = String(e.id);
  let bodyText = '';

  if (bodyMap.has(id)) {
    bodyText = bodyMap.get(id).body || '';
  } else if (fetched < maxBodyFetch) {
    try {
      const cmd = [himalayaBin, '-c', configPath, 'message', 'read', '--preview', '--no-headers', '--account', account, '--folder', e.folder || 'INBOX', id, '--output', 'json'];
      const raw = cp.execFileSync(cmd[0], cmd.slice(1), { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
      try { bodyText = JSON.parse(raw); } catch { bodyText = raw; }
      fetched++;
    } catch { bodyText = ''; }
  }

  // Find lifecycle stage from Phase 3
  const sample = (threadSamples.samples || []).find(s => s.thread_key === c.key);

  threadContexts.push({
    thread_key: c.key,
    count: c.count,
    latest_subject: e.subject || '',
    latest_from: e.from?.addr || '',
    latest_date: e.date || '',
    folder: e.folder || '',
    lifecycle_flow: sample?.flow || 'UNMODELED',
    lifecycle_stage: sample?.inferred_stage || 'unknown',
    lifecycle_stage_name: sample?.stage_name || '',
    lifecycle_confidence: sample?.confidence || 0,
    body_excerpt: String(bodyText).slice(0, 600),
    participants: [...new Set(threads.get(c.key).map(r => r.from?.addr || '').filter(Boolean))].slice(0, 5),
  });
}

// Human context
const factsRaw = readIfExists(factsPath);
const habitsRaw = readIfExists(habitsPath);
const calibrationRaw = readIfExists(calibrationPath);
const hasFacts = factsRaw && factsRaw !== 'facts: []';
const hasHabits = habitsRaw && habitsRaw !== 'habits: []';

const context = {
  generated_at: now.toLocaleString('sv-SE', {timeZone:'Asia/Shanghai'}).replace(' ','T') + '+08:00',
  lookback_days: lookbackDays,
  mail_address: mailAddress,
  recent_envelope_count: recent.length,
  thread_candidates: threadContexts.length,
  bodies_fetched_live: fetched,
  bodies_from_cache: threadContexts.filter(t => t.body_excerpt).length - fetched,
  lifecycle_model_summary: lifecycleRaw.slice(0, 2000) || null,
  persona_summary: personaRaw.slice(0, 800) || null,
  threads: threadContexts,
  human_context: {
    has_facts: hasFacts,
    has_habits: hasHabits,
    has_calibration: calibrationRaw.length > 50,
    manual_facts_raw: hasFacts ? factsRaw : null,
    manual_habits_raw: hasHabits ? habitsRaw : null,
    calibration_notes: calibrationRaw.length > 50 ? calibrationRaw.slice(0, 1500) : null,
  },
};

fs.writeFileSync(phase4Dir + '/context-pack.json', JSON.stringify(context, null, 2));
console.log('Context pack: ' + threadContexts.length + ' threads, ' + recent.length + ' recent envelopes');
console.log('  bodies: ' + fetched + ' fetched live, ' + (threadContexts.filter(t => t.body_excerpt).length - fetched) + ' from cache');
console.log('  human_context: facts=' + (hasFacts ? 'yes' : 'no') + ' habits=' + (hasHabits ? 'yes' : 'no'));
console.log('  -> ' + phase4Dir + '/context-pack.json');
NODE

echo ""
echo "Phase 4 loading complete."
echo "Output: ${PHASE4_DIR}/context-pack.json"
echo ""
echo "Next: bash scripts/phase4_thinking.sh"
