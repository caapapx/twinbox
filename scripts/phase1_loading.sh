#!/usr/bin/env bash
# Phase 1 Loading: deterministic envelope + body pull → context-pack
# Output: runtime/context/phase1-context.json
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

CODE_ROOT="${TWINBOX_CODE_ROOT}"
STATE_ROOT="${TWINBOX_STATE_ROOT:-${TWINBOX_CANONICAL_ROOT}}"
ENV_FILE="${STATE_ROOT}/.env"
CONTEXT_DIR="${STATE_ROOT}/runtime/context"
RAW_DIR="${STATE_ROOT}/runtime/context/raw"
CONFIG_FILE="${STATE_ROOT}/runtime/himalaya/config.toml"

MAX_PAGES_PER_FOLDER=20
PAGE_SIZE=50
SAMPLE_BODY_COUNT=30
LOOKBACK_DAYS="${PIPELINE_LOOKBACK_DAYS:-7}"
FOLDER_FILTER=""
ACCOUNT_OVERRIDE=""

usage() {
  cat <<'USAGE'
Usage:
  bash scripts/phase1_loading.sh [options]

Pulls envelope metadata + body samples from mailbox via himalaya.
Outputs: runtime/context/phase1-context.json

Options:
  --account <name>               Override MAIL_ACCOUNT_NAME
  --folder <name>                Only scan one folder (default: all)
  --max-pages-per-folder <n>     Max pages per folder (default: 20)
  --page-size <n>                Page size for envelope list (default: 50)
  --sample-body-count <n>        Bodies to sample (default: 30)
  --lookback-days <n>            Keep only recent envelopes in the last N days (default: PIPELINE_LOOKBACK_DAYS or 7)
  -h, --help                     Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --account) ACCOUNT_OVERRIDE="${2:-}"; shift 2 ;;
    --folder) FOLDER_FILTER="${2:-}"; shift 2 ;;
    --max-pages-per-folder) MAX_PAGES_PER_FOLDER="${2:-}"; shift 2 ;;
    --page-size) PAGE_SIZE="${2:-}"; shift 2 ;;
    --sample-body-count) SAMPLE_BODY_COUNT="${2:-}"; shift 2 ;;
    --lookback-days) LOOKBACK_DAYS="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

mkdir -p "${CONTEXT_DIR}" "${RAW_DIR}"

# --- env + himalaya setup ---
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
FOLDERS_JSON="${RAW_DIR}/folders.json"

# --- Step 1: folder list ---
echo "Fetching folder list..."
"${HIMALAYA_BIN}" -c "${CONFIG_FILE}" folder list --account "${ACCOUNT}" --output json > "${FOLDERS_JSON}"

mapfile -t FOLDERS < <(node -e '
  const rows = JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"));
  for (const r of rows) console.log(r.name);
' "${FOLDERS_JSON}")

if [[ -n "${FOLDER_FILTER}" ]]; then
  FOLDERS=("${FOLDER_FILTER}")
fi

echo "Folders: ${FOLDERS[*]}"

# --- Step 2: paginated envelope fetch ---
: > "${RAW_DIR}/all-pages.ndjson"

for folder in "${FOLDERS[@]}"; do
  safe_folder="$(printf '%s' "${folder}" | tr '/ ' '__')"
  for ((page=1; page<=MAX_PAGES_PER_FOLDER; page++)); do
    page_out="${RAW_DIR}/envelopes-${safe_folder}-p${page}.json"
    page_err="${RAW_DIR}/envelopes-${safe_folder}-p${page}.stderr.log"

    if ! "${HIMALAYA_BIN}" -c "${CONFIG_FILE}" envelope list \
        --account "${ACCOUNT}" --folder "${folder}" \
        --page "${page}" --page-size "${PAGE_SIZE}" \
        --output json > "${page_out}" 2> "${page_err}"; then
      if rg -qi "out of bound|out-of-bound|out of range" "${page_err}" 2>/dev/null; then
        break
      fi
      echo "Warn: envelope list failed for folder=${folder}, page=${page}" >&2
      break
    fi

    count="$(node -e '
      const a = JSON.parse(require("fs").readFileSync(process.argv[1],"utf8"));
      console.log(Array.isArray(a) ? a.length : 0);
    ' "${page_out}")"

    if [[ "${count}" -eq 0 ]]; then break; fi

    printf '{"folder":%s,"page":%s,"path":%s}\n' \
      "$(node -p 'JSON.stringify(process.argv[1])' "${folder}")" \
      "${page}" \
      "$(node -p 'JSON.stringify(process.argv[1])' "${page_out}")" \
      >> "${RAW_DIR}/all-pages.ndjson"

    if [[ "${count}" -lt "${PAGE_SIZE}" ]]; then break; fi
  done
done

# --- Step 3: merge envelopes ---
ENVELOPES_JSON="${RAW_DIR}/envelopes-merged.json"
node - <<'NODE' "${RAW_DIR}/all-pages.ndjson" "${ENVELOPES_JSON}" "${LOOKBACK_DAYS}"
const fs = require('fs');
const [ndjsonPath, outPath, lookbackDaysRaw] = process.argv.slice(2);
const lookbackDays = Number(lookbackDaysRaw);
const lines = fs.readFileSync(ndjsonPath, 'utf8').trim();
const items = [];
if (lines) {
  for (const line of lines.split('\n')) {
    const ref = JSON.parse(line);
    const rows = JSON.parse(fs.readFileSync(ref.path, 'utf8'));
    for (const r of rows) {
      items.push({ ...r, folder: ref.folder, source_page: ref.page });
    }
  }
}
function parseDate(value) {
  if (!value) return null;
  const d = new Date(String(value).replace(' ', 'T'));
  return Number.isNaN(d.getTime()) ? null : d;
}
const filtered = (Number.isFinite(lookbackDays) && lookbackDays > 0)
  ? items.filter((item) => {
      const dt = parseDate(item.date);
      if (!dt) return false;
      const cutoff = Date.now() - lookbackDays * 86400000;
      return dt.getTime() >= cutoff;
    })
  : items;
fs.writeFileSync(outPath, JSON.stringify(filtered, null, 2));
console.log(`Merged ${filtered.length} envelopes (lookback_days=${Number.isFinite(lookbackDays) && lookbackDays > 0 ? lookbackDays : 'all'})`);
NODE

# --- Step 4: sample bodies ---
BODIES_JSON="${RAW_DIR}/sample-bodies.json"
echo "Sampling ${SAMPLE_BODY_COUNT} message bodies..."
node - <<'NODE' "${ENVELOPES_JSON}" "${BODIES_JSON}" "${SAMPLE_BODY_COUNT}" "${HIMALAYA_BIN}" "${CONFIG_FILE}" "${ACCOUNT}"
const fs = require('fs');
const cp = require('child_process');
const [envPath, outPath, sampleCountRaw, bin, config, account] = process.argv.slice(2);
const envelopes = JSON.parse(fs.readFileSync(envPath, 'utf8'));
const sampleCount = Number(sampleCountRaw);
const samples = envelopes.slice(0, Math.max(0, sampleCount));
const out = [];
for (const e of samples) {
  const id = String(e.id);
  const folder = e.folder || 'INBOX';
  try {
    const cmd = [
      bin, '-c', config,
      'message', 'read', '--preview',
      '--account', account, '--folder', folder,
      id, '--output', 'json',
    ];
    const raw = cp.execFileSync(cmd[0], cmd.slice(1), {
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']
    });
    let body = '';
    try { body = JSON.parse(raw); } catch { body = ''; }
    out.push({ id, folder, subject: e.subject || '', body: String(body).slice(0, 3000) });
  } catch {
    out.push({ id, folder, subject: e.subject || '', body: '' });
  }
}
fs.writeFileSync(outPath, JSON.stringify(out, null, 2));
console.log(`Sampled ${out.length} bodies`);
NODE

# --- Step 5: build context-pack ---
echo "Building context-pack..."
node - <<'NODE' "${ENVELOPES_JSON}" "${BODIES_JSON}" "${FOLDERS_JSON}" "${CONTEXT_DIR}/phase1-context.json" "${MAIL_ADDRESS:-}" "${LOOKBACK_DAYS}"
const fs = require('fs');
const [envPath, bodiesPath, foldersPath, outPath, mailAddress, lookbackDaysRaw] = process.argv.slice(2);

const envelopes = JSON.parse(fs.readFileSync(envPath, 'utf8'));
const bodies = JSON.parse(fs.readFileSync(bodiesPath, 'utf8'));
const folders = JSON.parse(fs.readFileSync(foldersPath, 'utf8'));
const lookbackDays = Number(lookbackDaysRaw);

const ownDomain = (mailAddress.split('@')[1] || '').toLowerCase();

// Build envelope summaries (strip raw page refs)
const envelopeSummaries = envelopes.map(e => ({
  id: String(e.id),
  folder: e.folder || 'INBOX',
  subject: e.subject || '',
  from_name: (e.from && e.from.name) || '',
  from_addr: (e.from && e.from.addr) || '',
  date: e.date || '',
  has_attachment: !!e.has_attachment,
}));

// Body map keyed by id
const bodyMap = {};
for (const b of bodies) {
  bodyMap[String(b.id)] = { subject: b.subject || '', body: b.body || '' };
}

const contextPack = {
  generated_at: new Date().toLocaleString('sv-SE', {timeZone:'Asia/Shanghai'}).replace(' ','T') + '+08:00',
  owner_domain: ownDomain,
  lookback_days: Number.isFinite(lookbackDays) && lookbackDays > 0 ? lookbackDays : null,
  stats: {
    total_envelopes: envelopes.length,
    sampled_bodies: bodies.length,
    folders_scanned: folders.map(f => f.name),
  },
  envelopes: envelopeSummaries,
  sampled_bodies: bodyMap,
};

fs.writeFileSync(outPath, JSON.stringify(contextPack, null, 2));
console.log(`Context-pack written: ${outPath}`);
console.log(`  ${envelopes.length} envelopes, ${bodies.length} body samples`);
NODE

PHASE1_RAW_DIR="${STATE_ROOT}/runtime/validation/phase-1/raw"
mkdir -p "${PHASE1_RAW_DIR}"
cp -f "${RAW_DIR}/envelopes-merged.json" "${PHASE1_RAW_DIR}/envelopes-merged.json"
cp -f "${RAW_DIR}/sample-bodies.json" "${PHASE1_RAW_DIR}/sample-bodies.json"
cp -f "${RAW_DIR}/folders.json" "${PHASE1_RAW_DIR}/folders.json"
cp -f "${RAW_DIR}/all-pages.ndjson" "${PHASE1_RAW_DIR}/all-pages.ndjson"

echo ""
echo "Phase 1 Loading complete."
echo "  Lookback days: ${LOOKBACK_DAYS}"
echo "  Output: runtime/context/phase1-context.json"
