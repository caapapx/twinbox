#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

ROOT_DIR="${TWINBOX_CANONICAL_ROOT}"
ENV_FILE="${ROOT_DIR}/.env"
RUNTIME_DIR="${ROOT_DIR}/runtime/himalaya"
CONFIG_FILE="${RUNTIME_DIR}/config.toml"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing .env at ${ENV_FILE}"
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

mkdir -p "${RUNTIME_DIR}"

cat > "${CONFIG_FILE}" <<EOF
display-name = "${MAIL_DISPLAY_NAME}"
downloads-dir = "${RUNTIME_DIR}/downloads"

[accounts.${MAIL_ACCOUNT_NAME}]
email = "${MAIL_ADDRESS}"
default = true
display-name = "${MAIL_DISPLAY_NAME}"

backend.type = "imap"
backend.host = "${IMAP_HOST}"
backend.port = ${IMAP_PORT}
backend.encryption.type = "${IMAP_ENCRYPTION}"
backend.login = "${IMAP_LOGIN}"
backend.auth.type = "password"
backend.auth.raw = "${IMAP_PASS}"

message.send.backend.type = "smtp"
message.send.backend.host = "${SMTP_HOST}"
message.send.backend.port = ${SMTP_PORT}
message.send.backend.encryption.type = "${SMTP_ENCRYPTION}"
message.send.backend.login = "${SMTP_LOGIN}"
message.send.backend.auth.type = "password"
message.send.backend.auth.raw = "${SMTP_PASS}"
EOF

echo "Rendered ${CONFIG_FILE}"
