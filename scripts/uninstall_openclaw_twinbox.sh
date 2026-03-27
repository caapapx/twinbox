#!/usr/bin/env bash
# Completely remove Twinbox × OpenClaw integration from this machine.
# Removes: systemd units, OpenClaw cron jobs, sessions, skill file,
#          openclaw.json entries, ~/.config/twinbox/, runtime state.
# Does NOT uninstall the twinbox Python package (pass --with-pip to do so).
#
# Usage:
#   bash scripts/uninstall_openclaw_twinbox.sh [--dry-run] [--with-pip]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CODE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/twinbox"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
OPENCLAW_SKILLS_DIR="${HOME}/.openclaw/skills/twinbox"
OPENCLAW_SESSIONS_DIR="${HOME}/.openclaw/agents/twinbox/sessions"
OPENCLAW_JSON="${HOME}/.openclaw/openclaw.json"
STATE_ROOT="${CODE_ROOT}"

DRY_RUN=0
WITH_PIP=0
for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=1 ;;
    --with-pip) WITH_PIP=1 ;;
    --help|-h)
      echo "Usage: bash scripts/uninstall_openclaw_twinbox.sh [--dry-run] [--with-pip]"
      exit 0 ;;
  esac
done

run() {
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

echo "=== Twinbox × OpenClaw uninstall ==="
[[ "${DRY_RUN}" -eq 1 ]] && echo "(dry-run mode — no changes will be made)"
echo ""

# 1. Stop and disable systemd timer/service
echo "--- [1/8] systemd bridge units ---"
for unit in twinbox-openclaw-bridge.timer twinbox-openclaw-bridge.service; do
  if systemctl --user is-active "${unit}" &>/dev/null; then
    echo "Stopping ${unit}"
    run systemctl --user stop "${unit}"
  fi
  if systemctl --user is-enabled "${unit}" &>/dev/null; then
    echo "Disabling ${unit}"
    run systemctl --user disable "${unit}"
  fi
done
run systemctl --user daemon-reload

# 2. Remove systemd unit symlinks
echo ""
echo "--- [2/8] systemd unit symlinks ---"
for f in "${SYSTEMD_USER_DIR}/twinbox-openclaw-bridge.service" \
          "${SYSTEMD_USER_DIR}/twinbox-openclaw-bridge.timer"; do
  if [[ -e "${f}" || -L "${f}" ]]; then
    echo "Removing ${f}"
    run rm -f "${f}"
  fi
done

# 3. Delete OpenClaw cron jobs matching twinbox
echo ""
echo "--- [3/8] OpenClaw cron jobs ---"
if command -v openclaw &>/dev/null; then
  cron_json="$(openclaw cron list --all --json 2>/dev/null || echo '{}')"
  # Extract job IDs whose systemEvent text contains "twinbox.schedule"
  job_ids="$(echo "${cron_json}" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for job in data.get('jobs', []):
    payload = job.get('payload', {})
    if payload.get('kind') == 'systemEvent':
        text = payload.get('text', '')
        try:
            ev = json.loads(text)
            if ev.get('kind') == 'twinbox.schedule':
                print(job['id'])
        except Exception:
            pass
" 2>/dev/null || true)"
  if [[ -z "${job_ids}" ]]; then
    echo "No twinbox cron jobs found."
  else
    while IFS= read -r jid; do
      [[ -z "${jid}" ]] && continue
      echo "Deleting cron job ${jid}"
      run openclaw cron delete "${jid}"
    done <<< "${job_ids}"
  fi
else
  echo "openclaw not found in PATH; skipping cron cleanup."
fi

# 4. Delete OpenClaw agent sessions
echo ""
echo "--- [4/8] OpenClaw twinbox sessions ---"
if [[ -d "${OPENCLAW_SESSIONS_DIR}" ]]; then
  echo "Removing ${OPENCLAW_SESSIONS_DIR}"
  run rm -rf "${OPENCLAW_SESSIONS_DIR}"
else
  echo "No sessions directory found."
fi

# 5. Remove OpenClaw skill file
echo ""
echo "--- [5/8] OpenClaw skill file ---"
if [[ -d "${OPENCLAW_SKILLS_DIR}" ]]; then
  echo "Removing ${OPENCLAW_SKILLS_DIR}"
  run rm -rf "${OPENCLAW_SKILLS_DIR}"
else
  echo "Skill directory not found."
fi

# 6. Remove twinbox entries from openclaw.json
echo ""
echo "--- [6/8] openclaw.json entries ---"
if [[ -f "${OPENCLAW_JSON}" ]]; then
  echo "Removing skills.entries.twinbox and plugins twinbox-task-tools from ${OPENCLAW_JSON}"
  if [[ "${DRY_RUN}" -eq 0 ]]; then
    python3 - "${OPENCLAW_JSON}" <<'PYEOF'
import json, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
# Remove skill entry
skills = data.get("skills", {})
entries = skills.get("entries", {})
entries.pop("twinbox", None)
# Remove plugin entry
plugins = data.get("plugins", {})
plugin_entries = plugins.get("entries", {})
plugin_entries.pop("twinbox-task-tools", None)
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")
print("Done.")
PYEOF
  fi
else
  echo "openclaw.json not found."
fi

# 7. Remove ~/.config/twinbox/
echo ""
echo "--- [7/8] ~/.config/twinbox/ ---"
if [[ -d "${CONFIG_DIR}" ]]; then
  echo "Removing ${CONFIG_DIR}"
  run rm -rf "${CONFIG_DIR}"
else
  echo "Config directory not found."
fi

# 8. Remove runtime state
echo ""
echo "--- [8/8] runtime state ---"
RUNTIME_DIR="${STATE_ROOT}/runtime"
if [[ -d "${RUNTIME_DIR}" ]]; then
  echo "Removing ${RUNTIME_DIR}"
  run rm -rf "${RUNTIME_DIR}"
else
  echo "Runtime directory not found."
fi

# Optional: uninstall Python package
if [[ "${WITH_PIP}" -eq 1 ]]; then
  echo ""
  echo "--- [+] pip uninstall ---"
  run pip3 uninstall -y twinbox-core 2>/dev/null || echo "Package not installed via pip."
fi

# Restart Gateway
echo ""
echo "--- Restarting OpenClaw Gateway ---"
if command -v openclaw &>/dev/null; then
  run openclaw gateway restart || echo "Gateway restart failed or not running."
else
  echo "openclaw not found; skipping gateway restart."
fi

echo ""
echo "=== Uninstall complete ==="
[[ "${DRY_RUN}" -eq 1 ]] && echo "(dry-run — no changes were made)"
