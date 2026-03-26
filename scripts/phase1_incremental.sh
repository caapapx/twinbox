#!/usr/bin/env bash
# Phase 1 Incremental: UID watermark sync + context merge for daytime-sync
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/python_common.sh"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

CODE_ROOT="${TWINBOX_CODE_ROOT}"
STATE_ROOT="${TWINBOX_STATE_ROOT:-${TWINBOX_CANONICAL_ROOT}}"
ENV_FILE="${STATE_ROOT}/.env"
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
  bash scripts/phase1_incremental.sh [options]

Runs Phase 1 daytime incremental sync with UID watermarks.
Falls back to the existing full Phase 1 loader when UIDVALIDITY requires a rescan.

Options:
  --account <name>               Override MAIL_ACCOUNT_NAME
  --folder <name>                Only scan one folder (default: all)
  --max-pages-per-folder <n>     Accepted for compatibility with phase1_loading.sh
  --page-size <n>                Accepted for compatibility with phase1_loading.sh
  --sample-body-count <n>        Bodies to sample from newly fetched messages (default: 30)
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

mkdir -p "${RAW_DIR}"

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
    echo "himalaya CLI not found" >&2
    exit 1
  fi
else
  HIMALAYA_BIN="$(command -v himalaya)"
fi

ACCOUNT="${ACCOUNT_OVERRIDE:-${MAIL_ACCOUNT_NAME:-myTwinbox}}"
: "${MAIL_ADDRESS:?Missing MAIL_ADDRESS after mailbox validation.}"
FOLDERS_JSON="${RAW_DIR}/folders.json"

echo "Fetching folder list for incremental sync..."
"${HIMALAYA_BIN}" -c "${CONFIG_FILE}" folder list --account "${ACCOUNT}" --output json > "${FOLDERS_JSON}"

if [[ -n "${FOLDER_FILTER}" ]]; then
  node - <<'NODE' "${FOLDERS_JSON}" "${FOLDER_FILTER}"
const fs = require('fs');
const [path, wanted] = process.argv.slice(2);
fs.writeFileSync(path, JSON.stringify([{ name: wanted }], null, 2));
NODE
fi

set +e
_twinbox_python -m twinbox_core.imap_incremental \
  --state-root "${STATE_ROOT}" \
  --folders-json "${FOLDERS_JSON}" \
  --account "${ACCOUNT}" \
  --config "${CONFIG_FILE}" \
  --himalaya-bin "${HIMALAYA_BIN}" \
  --sample-body-count "${SAMPLE_BODY_COUNT}" \
  --lookback-days "${LOOKBACK_DAYS}"
status=$?
set -e

if [[ "${status}" -eq 20 ]]; then
  echo "Incremental sync requested full fallback; running phase1_loading.sh..."
  fallback_argv=(
    bash "${SCRIPT_DIR}/phase1_loading.sh"
    --account "${ACCOUNT}"
    --max-pages-per-folder "${MAX_PAGES_PER_FOLDER}"
    --page-size "${PAGE_SIZE}"
    --sample-body-count "${SAMPLE_BODY_COUNT}"
    --lookback-days "${LOOKBACK_DAYS}"
  )
  if [[ -n "${FOLDER_FILTER}" ]]; then
    fallback_argv+=(--folder "${FOLDER_FILTER}")
  fi
  exec "${fallback_argv[@]}"
fi

exit "${status}"
