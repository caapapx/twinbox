#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/python_common.sh"
source "${SCRIPT_DIR}/twinbox_paths.sh"
twinbox_init_roots "${BASH_SOURCE[0]}"

ROOT_DIR="${TWINBOX_STATE_ROOT:-${TWINBOX_CANONICAL_ROOT}}"

INTERACTIVE=0
SHOW_CHAT_TEMPLATE=0
JSON_OUTPUT=0
FOLDER="INBOX"
PAGE_SIZE=5
ACCOUNT_OVERRIDE=""

usage() {
  cat <<'EOF'
Usage:
  bash scripts/preflight_mailbox_smoke.sh [options]

Options:
  --interactive            Deprecated; OpenClaw should collect env fields, then rerun preflight
  --headless               Alias for the default non-interactive mode
  --chat-template          Print a mailbox setup template and exit
  --json                   Emit machine-readable JSON
  --account <name>         Override MAIL_ACCOUNT_NAME for smoke test
  --folder <name>          Folder for read-only envelope list (default: INBOX)
  --page-size <n>          Envelope list page size (default: 5)
  -h, --help               Show this help
EOF
}

print_chat_template() {
  cat <<'EOF'
请按以下字段一次性回复（用于邮箱登录预检，只读模式）：
MAIL_ADDRESS=...
IMAP_HOST=...
IMAP_PORT=993
IMAP_LOGIN=...
IMAP_PASS=...
SMTP_HOST=...
SMTP_PORT=465
SMTP_LOGIN=...
SMTP_PASS=...

可选字段（未提供则使用默认值）：
MAIL_ACCOUNT_NAME=myTwinbox
MAIL_DISPLAY_NAME=myTwinbox
IMAP_ENCRYPTION=tls
SMTP_ENCRYPTION=tls
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interactive)
      INTERACTIVE=1
      shift
      ;;
    --headless)
      shift
      ;;
    --chat-template)
      SHOW_CHAT_TEMPLATE=1
      shift
      ;;
    --json)
      JSON_OUTPUT=1
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

if [[ "${INTERACTIVE}" -eq 1 ]]; then
  echo "Note: --interactive is deprecated. Collect fields in OpenClaw or export them in the shell, then rerun preflight." >&2
fi

cmd=(
  -m twinbox_core.mailbox preflight
  --state-root "${ROOT_DIR}"
  --folder "${FOLDER}"
  --page-size "${PAGE_SIZE}"
)

if [[ -n "${ACCOUNT_OVERRIDE}" ]]; then
  cmd+=(--account "${ACCOUNT_OVERRIDE}")
fi

if [[ "${JSON_OUTPUT}" -eq 1 ]]; then
  cmd+=(--json)
fi

_twinbox_python "${cmd[@]}"
