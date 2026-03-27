#!/usr/bin/env bash
# Pack src/twinbox_core into a gzip tarball for Go install / offline vendor seed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VERSION="$(python3 -c "import tomllib, pathlib; p=pathlib.Path('$ROOT/pyproject.toml'); d=tomllib.loads(p.read_text()); print(d['project']['version'])")"
OUT="${1:-$ROOT/dist/twinbox_core-${VERSION}.tar.gz}"
mkdir -p "$(dirname "$OUT")"
tar -czf "$OUT" -C "$ROOT/src" twinbox_core
echo "$OUT"
