#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

ROOT_DIR="${TWINBOX_CANONICAL_ROOT}"
ENV_FILE="${ROOT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing .env at ${ENV_FILE}"
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

required=(
  MAIL_ACCOUNT_NAME
  MAIL_DISPLAY_NAME
  MAIL_ADDRESS
  IMAP_HOST
  IMAP_PORT
  IMAP_ENCRYPTION
  IMAP_LOGIN
  IMAP_PASS
  SMTP_HOST
  SMTP_PORT
  SMTP_ENCRYPTION
  SMTP_LOGIN
  SMTP_PASS
)

missing=0
for key in "${required[@]}"; do
  if [[ -z "${!key:-}" ]]; then
    echo "Missing required key: ${key}"
    missing=1
  fi
done

if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

echo "All required .env keys are present."
