#!/usr/bin/env bash
# Pack the Go ``twinbox install --archive`` bundle: Python package + OpenClaw skill assets.
#
# Layout inside the tarball (all extracted under ``$TWINBOX_STATE_ROOT/vendor/``):
#   twinbox_core/          — from src/twinbox_core
#   openclaw-skill/        — fragment, plugin, docs (node_modules excluded)
#   SKILL.md               — repo-root skill manifest (deploy copies to state + OpenClaw)
#   scripts/install_openclaw_twinbox_init.sh — bootstrap; ``install`` writes ~/.config/twinbox/code-root → vendor dir
#
# Output filename stays twinbox_core-<version>.tar.gz for compatibility with existing docs/scripts.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VERSION="$(python3 -c "import tomllib, pathlib; p=pathlib.Path('$ROOT/pyproject.toml'); d=tomllib.loads(p.read_text()); print(d['project']['version'])")"
OUT="${1:-$ROOT/dist/twinbox_core-${VERSION}.tar.gz}"
mkdir -p "$(dirname "$OUT")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/scripts"
cp "$ROOT/scripts/install_openclaw_twinbox_init.sh" "$TMP/scripts/"
tar -czf "$OUT" \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='openclaw-skill/plugin-twinbox-task/node_modules' \
  -C "$ROOT/src" twinbox_core \
  -C "$ROOT" openclaw-skill SKILL.md \
  -C "$TMP" scripts
echo "$OUT"
