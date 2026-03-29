#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

CHECK_NAMES=(
  "python-runtime"
  "python-loading"
  "python-openclaw-deploy"
  "go-entrypoint"
)

CHECK_COMMANDS=(
  "python3 -m pytest tests/test_daemon_rpc.py tests/test_daemon_handlers_unit.py tests/test_daemon_rpc_protocol.py tests/test_vendor_install.py -q"
  "python3 -m pytest tests/test_loading_pipeline.py tests/test_mailbox.py -q"
  "python3 -m pytest tests/test_openclaw_deploy_steps.py tests/test_openclaw_deploy.py -q"
  "cd cmd/twinbox-go && go test ./..."
)

usage() {
  cat <<'EOF'
Usage: bash scripts/verify_runtime_slice.sh [--list|--dry-run]

Options:
  --list     Print the named verification checks and exit
  --dry-run  Print the commands that would run and exit
EOF
}

mode="run"
case "${1:-}" in
  "")
    ;;
  --list)
    mode="list"
    ;;
  --dry-run)
    mode="dry-run"
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

for i in "${!CHECK_NAMES[@]}"; do
  name="${CHECK_NAMES[$i]}"
  cmd="${CHECK_COMMANDS[$i]}"
  case "$mode" in
    list)
      printf '%s\n' "$name"
      ;;
    dry-run)
      printf '[%s] %s\n' "$name" "$cmd"
      ;;
    run)
      printf '==> [%s] %s\n' "$name" "$cmd"
      (
        cd "$ROOT"
        bash -lc "$cmd"
      )
      ;;
  esac
done
