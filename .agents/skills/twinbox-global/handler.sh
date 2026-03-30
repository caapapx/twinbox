#!/usr/bin/env bash
# Twinbox global skill handler

set -euo pipefail

COMMAND="${1:-latest}"

case "$COMMAND" in
  latest|"")
    twinbox task latest-mail --json
    ;;
  todo)
    twinbox task todo --json
    ;;
  weekly)
    twinbox task weekly --json
    ;;
  status)
    twinbox daemon status --json
    ;;
  *)
    echo "Unknown command: $COMMAND"
    echo "Usage: /twinbox [latest|todo|weekly|status]"
    exit 1
    ;;
esac
