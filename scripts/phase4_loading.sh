#!/usr/bin/env bash
# Phase 4 Loading: fetch recent thread bodies + build context for LLM value output
# Deterministic I/O, no LLM.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

CODE_ROOT="${TWINBOX_CODE_ROOT}"
STATE_ROOT="${TWINBOX_STATE_ROOT:-${TWINBOX_CANONICAL_ROOT}}"
ENV_FILE="${STATE_ROOT}/.env"
CONFIG_FILE="${STATE_ROOT}/runtime/himalaya/config.toml"
PHASE1_DIR="${STATE_ROOT}/runtime/validation/phase-1"
PHASE3_DIR="${STATE_ROOT}/runtime/validation/phase-3"
PHASE4_DIR="${STATE_ROOT}/runtime/validation/phase-4"

ENVELOPES="${PHASE1_DIR}/raw/envelopes-merged.json"
BODIES="${PHASE1_DIR}/raw/sample-bodies.json"
CENSUS="${PHASE1_DIR}/mailbox-census.json"
LIFECYCLE="${PHASE3_DIR}/lifecycle-model.yaml"
THREAD_SAMPLES="${PHASE3_DIR}/thread-stage-samples.json"
PERSONA="${STATE_ROOT}/runtime/validation/phase-2/persona-hypotheses.yaml"

MANUAL_FACTS="${STATE_ROOT}/runtime/context/manual-facts.yaml"
MANUAL_HABITS="${STATE_ROOT}/runtime/context/manual-habits.yaml"
CALIBRATION="${STATE_ROOT}/runtime/context/instance-calibration-notes.md"
MATERIAL_EXTRACTS="${STATE_ROOT}/runtime/context/material-extracts"

LOOKBACK_DAYS="${PIPELINE_LOOKBACK_DAYS:-7}"
MAX_BODY_FETCH=24
MAX_THREAD_CANDIDATES="${PIPELINE_PHASE4_MAX_THREADS:-45}"
ACCOUNT_OVERRIDE=""

usage() {
  cat <<'USAGE'
Usage: bash scripts/phase4_loading.sh [options]
Options:
  --account <name>         Override MAIL_ACCOUNT_NAME
  --lookback-days <n>      Lookback window (default: PIPELINE_LOOKBACK_DAYS or 7)
  --max-body-fetch <n>     Max bodies to fetch live (default: 24)
  --max-thread-candidates <n>  Max candidate threads kept for Phase 4 (default: PIPELINE_PHASE4_MAX_THREADS or 45)
  -h, --help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --account) ACCOUNT_OVERRIDE="${2:-}"; shift 2 ;;
    --lookback-days) LOOKBACK_DAYS="${2:-}"; shift 2 ;;
    --max-body-fetch) MAX_BODY_FETCH="${2:-}"; shift 2 ;;
    --max-thread-candidates) MAX_THREAD_CANDIDATES="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

mkdir -p "${PHASE4_DIR}"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  source "${ENV_FILE}"
  set +a
fi
bash "${CODE_ROOT}/scripts/check_env.sh"
bash "${CODE_ROOT}/scripts/render_himalaya_config.sh"

if ! command -v himalaya >/dev/null 2>&1; then
  if [[ -x "${STATE_ROOT}/runtime/bin/himalaya" ]]; then
    HIMALAYA_BIN="${STATE_ROOT}/runtime/bin/himalaya"
  else
    echo "himalaya CLI not found"; exit 1
  fi
else
  HIMALAYA_BIN="$(command -v himalaya)"
fi

ACCOUNT="${ACCOUNT_OVERRIDE:-${MAIL_ACCOUNT_NAME:-myTwinbox}}"
: "${MAIL_ADDRESS:?Missing MAIL_ADDRESS after mailbox validation.}"

for required in "${ENVELOPES}" "${THREAD_SAMPLES}"; do
  if [[ ! -f "${required}" ]]; then
    echo "Missing: ${required}"; echo "Run Phase 1-3 first."; exit 1
  fi
done

mkdir -p "${MATERIAL_EXTRACTS}"

# Build context pack: recent threads + live body fetch + lifecycle model + human context
node - <<'NODE' "${ENVELOPES}" "${BODIES}" "${THREAD_SAMPLES}" "${LIFECYCLE}" "${PERSONA}" "${CENSUS}" "${PHASE4_DIR}" "${HIMALAYA_BIN}" "${CONFIG_FILE}" "${ACCOUNT}" "${MAIL_ADDRESS}" "${LOOKBACK_DAYS}" "${MAX_BODY_FETCH}" "${MAX_THREAD_CANDIDATES}" "${MANUAL_FACTS}" "${MANUAL_HABITS}" "${CALIBRATION}" "${MATERIAL_EXTRACTS}"
const fs = require('fs');
const path = require('path');
const cp = require('child_process');
const [envelopesPath, bodiesPath, threadSamplesPath, lifecyclePath, personaPath, censusPath, phase4Dir, himalayaBin, configPath, account, mailAddress, lookbackDaysRaw, maxBodyFetchRaw, maxThreadCandidatesRaw, factsPath, habitsPath, calibrationPath, materialExtractsDir] = process.argv.slice(2);

function readMaterialExtractBundle(dir) {
  try {
    if (!fs.existsSync(dir)) return '';
    const names = fs.readdirSync(dir).filter((f) => f.endsWith('.extracted.md')).sort();
    let acc = '';
    for (const name of names) {
      const full = path.join(dir, name);
      acc += '\n\n<!-- ' + name + ' -->\n\n' + fs.readFileSync(full, 'utf8');
    }
    return acc.slice(0, 8000);
  } catch {
    return '';
  }
}

function readIfExists(p) {
  try { return fs.readFileSync(p, 'utf8').trim(); } catch { return ''; }
}

function extractPersonaHypotheses(text, limit = 3) {
  const matches = [...String(text || '').matchAll(/hypothesis:\s*"([^"]+)"/g)].map((match) => match[1].trim());
  return matches.slice(0, limit);
}

function extractBulletBlock(text, anchor, limit = 4) {
  const lines = String(text || '').split(/\r?\n/);
  const start = lines.findIndex((line) => line.includes(anchor));
  if (start < 0) return [];
  const bullets = [];
  for (let i = start + 1; i < lines.length && bullets.length < limit; i += 1) {
    const trimmed = lines[i].trim();
    if (!trimmed) {
      if (bullets.length > 0) break;
      continue;
    }
    if (trimmed.startsWith('## ') || trimmed.startsWith('### ')) break;
    if (trimmed.startsWith('- ')) {
      bullets.push(trimmed.slice(2).trim());
      continue;
    }
    if (bullets.length > 0) break;
  }
  return bullets;
}

const envelopes = JSON.parse(fs.readFileSync(envelopesPath, 'utf8'));
const existingBodies = JSON.parse(fs.readFileSync(bodiesPath, 'utf8'));
const threadSamples = JSON.parse(fs.readFileSync(threadSamplesPath, 'utf8'));
const lifecycleRaw = readIfExists(lifecyclePath);
const personaRaw = readIfExists(personaPath);
const censusRaw = readIfExists(censusPath);
const lookbackDays = Number(lookbackDaysRaw);
const maxBodyFetch = Number(maxBodyFetchRaw);
const maxThreadCandidates = Number(maxThreadCandidatesRaw);

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

function signalScore(subject, cachedBody) {
  const haystack = (String(subject || '') + '\n' + String(cachedBody || '')).toLowerCase();
  let score = 0;
  if (/(部署结果反馈|资源反馈|部署反馈)/i.test(haystack)) score += 6;
  if (/(周报|工作周报|交付周报|台账)/i.test(haystack)) score += 5;
  if (/(一次成功|问题反馈|风险|漏洞|整改|联调)/i.test(haystack)) score += 4;
  return score;
}

// Pick threads worth analyzing (multi-message or lifecycle-modeled), but keep
// signal-heavy single threads so deployment feedback / weekly summaries do not get crowded out.
const modeledKeys = new Set((threadSamples.samples || []).map(s => s.thread_key));
const ranked = [...threads.entries()]
  .map(([key, rows]) => ({
    key,
    count: rows.length,
    modeled: modeledKeys.has(key),
    latest: rows.sort((a, b) => new Date(b.date) - new Date(a.date))[0],
  }))
  .map((item) => {
    const cachedBody = bodyMap.get(String(item.latest.id))?.body || '';
    return {
      ...item,
      latest_ts: item.latest?.date ? new Date(item.latest.date).getTime() : 0,
      signal_score: signalScore(item.latest?.subject || item.key, cachedBody),
    };
  });

const primary = [...ranked]
  .sort((a, b) => (b.modeled ? 1 : 0) - (a.modeled ? 1 : 0) || b.count - a.count || b.signal_score - a.signal_score || b.latest_ts - a.latest_ts)
  .slice(0, maxThreadCandidates);
const signalHeavy = [...ranked]
  .filter((item) => item.signal_score > 0)
  .sort((a, b) => b.signal_score - a.signal_score || (b.modeled ? 1 : 0) - (a.modeled ? 1 : 0) || b.latest_ts - a.latest_ts)
  .slice(0, Math.min(12, maxThreadCandidates));
const candidateMap = new Map();
for (const item of [...primary, ...signalHeavy]) {
  candidateMap.set(item.key, item);
}
const candidates = [...candidateMap.values()]
  .sort((a, b) => (b.modeled ? 1 : 0) - (a.modeled ? 1 : 0) || b.signal_score - a.signal_score || b.count - a.count || b.latest_ts - a.latest_ts)
  .slice(0, maxThreadCandidates);

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
  
  // Find recipient_role from Phase 3 context pack if available
  let recipientRole = 'unknown';
  try {
    const phase3Context = JSON.parse(fs.readFileSync(phase4Dir.replace('phase-4', 'phase-3') + '/context-pack.json', 'utf8'));
    const p3Thread = (phase3Context.top_threads || []).find(t => t.thread_key === c.key);
    if (p3Thread && p3Thread.recipient_role) {
      recipientRole = p3Thread.recipient_role;
    }
  } catch (e) {
    // Ignore
  }

  threadContexts.push({
    thread_key: c.key,
    count: c.count,
    latest_subject: e.subject || '',
    latest_from: e.from?.addr || '',
    latest_date: e.date || '',
    folder: e.folder || '',
    recipient_role: recipientRole,
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
const materialBundle = readMaterialExtractBundle(materialExtractsDir);
const hasFacts = factsRaw && factsRaw !== 'facts: []';
const hasHabits = habitsRaw && habitsRaw !== 'habits: []';
const hasMaterialExtracts = materialBundle.trim().length > 50;
const ownerFocus = {
  primary_role_hypotheses: extractPersonaHypotheses(personaRaw, 3),
  weekly_brief_priorities: extractBulletBlock(calibrationRaw, '应优先看到', 4),
  demote_categories: [
    '与当前岗位主线无关的广播类通知',
    '培训、HR、泛宣传邮件（除非本周明确要求本人处理）',
  ],
};

const context = {
  generated_at: now.toLocaleString('sv-SE', {timeZone:'Asia/Shanghai'}).replace(' ','T') + '+08:00',
  lookback_days: lookbackDays,
  mail_address: mailAddress,
  recent_envelope_count: recent.length,
  thread_candidates: threadContexts.length,
  bodies_fetched_live: fetched,
  bodies_from_cache: threadContexts.filter(t => t.body_excerpt).length - fetched,
  lifecycle_model_summary: lifecycleRaw.slice(0, 2000) || null,
  persona_summary: personaRaw.slice(0, 2000) || null,
  owner_focus: ownerFocus,
  threads: threadContexts,
  human_context: {
    has_facts: hasFacts,
    has_habits: hasHabits,
    has_calibration: calibrationRaw.length > 50,
    has_material_extracts: hasMaterialExtracts,
    manual_facts_raw: hasFacts ? factsRaw : null,
    manual_habits_raw: hasHabits ? habitsRaw : null,
    calibration_notes: calibrationRaw.length > 50 ? calibrationRaw.slice(0, 2500) : null,
    material_extracts_notes: hasMaterialExtracts ? materialBundle : null,
  },
};

fs.writeFileSync(phase4Dir + '/context-pack.json', JSON.stringify(context, null, 2));
console.log('Context pack: ' + threadContexts.length + ' threads, ' + recent.length + ' recent envelopes');
console.log('  bodies: ' + fetched + ' fetched live, ' + (threadContexts.filter(t => t.body_excerpt).length - fetched) + ' from cache');
console.log('  human_context: facts=' + (hasFacts ? 'yes' : 'no') + ' habits=' + (hasHabits ? 'yes' : 'no') + ' calibration=' + (calibrationRaw.length > 50 ? 'yes' : 'no') + ' materials=' + (hasMaterialExtracts ? 'yes' : 'no'));
console.log('  -> ' + phase4Dir + '/context-pack.json');
NODE

echo ""
echo "Applying Phase 3.5 Routing Rules..."
source "${SCRIPT_DIR}/python_common.sh"
_twinbox_python -m twinbox_core.routing_rules \
  --context-pack "${PHASE4_DIR}/context-pack.json" \
  --rules "${STATE_ROOT}/config/routing-rules.yaml" \
  --output "${PHASE4_DIR}/context-pack.json" \
  --env-file "${ENV_FILE}"

echo ""
echo "Phase 4 loading complete."
echo "Lookback days: ${LOOKBACK_DAYS}"
echo "Output: ${PHASE4_DIR}/context-pack.json"
echo ""
echo "Next: bash scripts/phase4_thinking.sh"
