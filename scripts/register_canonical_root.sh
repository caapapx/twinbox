#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"

ROOT_OVERRIDE=""
PRINT_ONLY=false
CLEAR=false

usage() {
  cat <<'USAGE'
Usage: bash scripts/register_canonical_root.sh [options]
Options:
  --root <path>   Register this path instead of the current checkout
  --print         Print the currently configured canonical root
  --clear         Remove the stored canonical root
  -h, --help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT_OVERRIDE="${2:-}"; shift 2 ;;
    --print) PRINT_ONLY=true; shift ;;
    --clear) CLEAR=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

CONFIG_FILE="$(twinbox_canonical_root_file)"

if [[ "${PRINT_ONLY}" == "true" ]]; then
  if [[ -f "${CONFIG_FILE}" ]]; then
    sed -n '1p' "${CONFIG_FILE}"
  fi
  exit 0
fi

if [[ "${CLEAR}" == "true" ]]; then
  rm -f "${CONFIG_FILE}"
  echo "Cleared ${CONFIG_FILE}"
  exit 0
fi

TARGET_ROOT="${ROOT_OVERRIDE:-$(cd "${SCRIPT_DIR}/.." && pwd -P)}"
TARGET_ROOT="$(twinbox_resolve_existing_dir "${TARGET_ROOT}")" || {
  echo "Invalid root: ${TARGET_ROOT}" >&2
  exit 1
}

if [[ ! -f "${TARGET_ROOT}/scripts/phase4_loading.sh" ]]; then
  echo "Not a twinbox checkout: ${TARGET_ROOT}" >&2
  exit 1
fi

mkdir -p "$(dirname "${CONFIG_FILE}")"
printf '%s\n' "${TARGET_ROOT}" > "${CONFIG_FILE}"
echo "Registered canonical root: ${TARGET_ROOT}"
echo "Config file: ${CONFIG_FILE}"
