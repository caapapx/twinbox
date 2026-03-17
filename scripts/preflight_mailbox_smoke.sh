#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
RUNTIME_DIR="${ROOT_DIR}/runtime/validation/preflight"
REPORT_FILE="${ROOT_DIR}/docs/validation/preflight-mailbox-smoke-report.md"
OUTPUT_FILE="${RUNTIME_DIR}/mailbox-smoke.json"
STDERR_FILE="${RUNTIME_DIR}/mailbox-smoke.stderr.log"

INTERACTIVE=0
SHOW_CHAT_TEMPLATE=0
FOLDER="INBOX"
PAGE_SIZE=5
ACCOUNT_OVERRIDE=""

usage() {
  cat <<'EOF'
Usage:
  bash scripts/preflight_mailbox_smoke.sh [options]

Options:
  --interactive            Prompt for missing .env fields in terminal
  --headless               Do not prompt; fail if required fields are missing (default)
  --chat-template          Print a chat questionnaire template and exit
  --account <name>         Override MAIL_ACCOUNT_NAME for smoke test
  --folder <name>          Folder for read-only envelope list (default: INBOX)
  --page-size <n>          Envelope list page size (default: 5)
  -h, --help               Show this help
EOF
}

print_chat_template() {
  cat <<'EOF'
请按以下字段一次性回复（用于邮箱登录冒烟测试，全部只读）：
1. MAIL_ACCOUNT_NAME（如 work）
2. MAIL_DISPLAY_NAME（如 Work_Mail）
3. MAIL_ADDRESS
4. IMAP_HOST / IMAP_PORT / IMAP_ENCRYPTION
5. IMAP_LOGIN / IMAP_PASS（建议 app password）
6. SMTP_HOST / SMTP_PORT / SMTP_ENCRYPTION
7. SMTP_LOGIN / SMTP_PASS

回复格式建议（可直接粘贴）：
MAIL_ACCOUNT_NAME=...
MAIL_DISPLAY_NAME=...
MAIL_ADDRESS=...
IMAP_HOST=...
IMAP_PORT=993
IMAP_ENCRYPTION=tls
IMAP_LOGIN=...
IMAP_PASS=...
SMTP_HOST=...
SMTP_PORT=465
SMTP_ENCRYPTION=tls
SMTP_LOGIN=...
SMTP_PASS=...
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interactive)
      INTERACTIVE=1
      shift
      ;;
    --headless)
      INTERACTIVE=0
      shift
      ;;
    --chat-template)
      SHOW_CHAT_TEMPLATE=1
      shift
      ;;
    --account)
      ACCOUNT_OVERRIDE="${2:-}"
      shift 2
      ;;
    --folder)
      FOLDER="${2:-}"
      shift 2
      ;;
    --page-size)
      PAGE_SIZE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ "${SHOW_CHAT_TEMPLATE}" -eq 1 ]]; then
  print_chat_template
  exit 0
fi

mkdir -p "${RUNTIME_DIR}" "$(dirname "${REPORT_FILE}")"
: > "${STDERR_FILE}"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ROOT_DIR}/.env.example" "${ENV_FILE}"
  echo "Created ${ENV_FILE} from .env.example"
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

missing=()
for key in "${required[@]}"; do
  if [[ -z "${!key:-}" ]]; then
    missing+=("${key}")
  fi
done

upsert_env_key() {
  local key="$1"
  local val="$2"
  local escaped
  escaped="$(printf '%s' "${val}" | sed -e 's/[\/&]/\\&/g')"
  if grep -qE "^${key}=" "${ENV_FILE}"; then
    sed -i "s/^${key}=.*/${key}=${escaped}/" "${ENV_FILE}"
  else
    printf '%s=%s\n' "${key}" "${val}" >> "${ENV_FILE}"
  fi
}

if [[ "${#missing[@]}" -gt 0 ]]; then
  if [[ "${INTERACTIVE}" -eq 1 ]]; then
    echo "Missing required fields in .env: ${missing[*]}"
    for key in "${missing[@]}"; do
      if [[ "${key}" == *"_PASS" ]]; then
        read -r -s -p "Please input ${key}: " value
        echo
      else
        read -r -p "Please input ${key}: " value
      fi
      upsert_env_key "${key}" "${value}"
    done
    set -a
    source "${ENV_FILE}"
    set +a
  else
    echo "Missing required .env keys: ${missing[*]}"
    echo "Run interactive mode:"
    echo "  bash scripts/preflight_mailbox_smoke.sh --interactive"
    echo "Or print chat template:"
    echo "  bash scripts/preflight_mailbox_smoke.sh --chat-template"
    exit 1
  fi
fi

bash "${ROOT_DIR}/scripts/check_env.sh"
bash "${ROOT_DIR}/scripts/render_himalaya_config.sh"

if ! command -v himalaya >/dev/null 2>&1; then
  echo "himalaya CLI not found in PATH"
  exit 1
fi

ACCOUNT="${ACCOUNT_OVERRIDE:-${MAIL_ACCOUNT_NAME}}"
CMD=(
  himalaya
  --account "${ACCOUNT}"
  envelope list
  --folder "${FOLDER}"
  --page 1
  --page-size "${PAGE_SIZE}"
  --output json
)

status="success"
if ! "${CMD[@]}" > "${OUTPUT_FILE}" 2> "${STDERR_FILE}"; then
  status="failed"
fi

timestamp="$(date '+%Y-%m-%d %H:%M:%S %z')"
cat > "${REPORT_FILE}" <<EOF
# Preflight Mailbox Smoke Report

- time: ${timestamp}
- mode: $([[ "${INTERACTIVE}" -eq 1 ]] && echo "interactive" || echo "headless")
- account: ${ACCOUNT}
- folder: ${FOLDER}
- page_size: ${PAGE_SIZE}
- status: ${status}
- output_json: runtime/validation/preflight/mailbox-smoke.json
- stderr_log: runtime/validation/preflight/mailbox-smoke.stderr.log

## Command

\`\`\`bash
${CMD[*]}
\`\`\`

## Notes

- This preflight runs read-only envelope listing.
- It does not send, move, delete, archive, or flag messages.
EOF

if [[ "${status}" != "success" ]]; then
  echo "Preflight failed. See:"
  echo "  ${STDERR_FILE}"
  exit 1
fi

echo "Preflight succeeded."
echo "Report: ${REPORT_FILE}"
echo "Output: ${OUTPUT_FILE}"
