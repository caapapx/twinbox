#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CODE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
STATE_ROOT="${TWINBOX_STATE_ROOT:-${TWINBOX_CANONICAL_ROOT:-${CODE_ROOT}}}"
OPENCLAW_BIN="${OPENCLAW_BIN:-$(command -v openclaw)}"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
TWINBOX_CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/twinbox"
ENV_FILE="${TWINBOX_CONFIG_DIR}/twinbox-openclaw-bridge.env"
SERVICE_SRC="${CODE_ROOT}/openclaw-skill/twinbox-openclaw-bridge.service"
TIMER_SRC="${CODE_ROOT}/openclaw-skill/twinbox-openclaw-bridge.timer"
SERVICE_DST="${SYSTEMD_USER_DIR}/twinbox-openclaw-bridge.service"
TIMER_DST="${SYSTEMD_USER_DIR}/twinbox-openclaw-bridge.timer"

usage() {
  cat <<'EOF'
Usage:
  scripts/install_openclaw_bridge_user_units.sh [--no-start]

Install Twinbox OpenClaw bridge units into the current user's systemd directory,
write the environment file, reload systemd, and optionally enable/start the timer.
EOF
}

NO_START=0
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ "${1:-}" == "--no-start" ]]; then
  NO_START=1
fi

mkdir -p "${SYSTEMD_USER_DIR}" "${TWINBOX_CONFIG_DIR}"

cat > "${ENV_FILE}" <<EOF
TWINBOX_CODE_ROOT=${CODE_ROOT}
TWINBOX_STATE_ROOT=${STATE_ROOT}
TWINBOX_CANONICAL_ROOT=${STATE_ROOT}
OPENCLAW_BIN=${OPENCLAW_BIN}
EOF

ln -sfn "${SERVICE_SRC}" "${SERVICE_DST}"
ln -sfn "${TIMER_SRC}" "${TIMER_DST}"

systemctl --user daemon-reload

if [[ "${NO_START}" -eq 1 ]]; then
  systemctl --user enable twinbox-openclaw-bridge.timer >/dev/null
else
  systemctl --user enable --now twinbox-openclaw-bridge.timer >/dev/null
fi

echo "Installed:"
echo "  ${SERVICE_DST} -> ${SERVICE_SRC}"
echo "  ${TIMER_DST} -> ${TIMER_SRC}"
echo "  ${ENV_FILE}"
if [[ "${NO_START}" -eq 1 ]]; then
  echo "Timer enabled but not started."
else
  echo "Timer enabled and started."
fi
