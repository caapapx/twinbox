#!/usr/bin/env bash
# Pack the Go ``twinbox install --archive`` bundle: Python package + OpenClaw skill assets.
#
# Layout inside the tarball (all extracted under ``$TWINBOX_STATE_ROOT/vendor/``):
#   twinbox_core/          — from src/twinbox_core
#   integrations/openclaw/        — fragment, plugin, docs (node_modules excluded)
#   SKILL.md               — repo-root skill manifest (deploy copies to state + OpenClaw)
#   scripts/install_openclaw_twinbox_init.sh — bootstrap; Go ``install --archive`` writes ~/.twinbox/code-root → vendor dir
#
# Output filename stays twinbox_core-<version>.tar.gz for compatibility with existing docs/scripts.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
# Read version without tomllib (Python <3.11); keep in sync with [project].version in pyproject.toml.
VERSION="$(grep -E '^version[[:space:]]*=' "$ROOT/pyproject.toml" | head -1 | sed -E 's/^version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/')"
if [[ -z "${VERSION}" ]]; then
	echo "error: could not parse version from $ROOT/pyproject.toml" >&2
	exit 1
fi
OUT="${1:-$ROOT/dist/twinbox_core-${VERSION}.tar.gz}"
mkdir -p "$(dirname "$OUT")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/scripts"
cp "$ROOT/scripts/install_openclaw_twinbox_init.sh" "$TMP/scripts/"
tar -czf "$OUT" \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='integrations/openclaw/plugin-twinbox-task/node_modules' \
  -C "$ROOT/src" twinbox_core \
  -C "$ROOT" integrations/openclaw SKILL.md config \
  -C "$TMP" scripts
echo "$OUT"
