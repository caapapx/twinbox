#!/usr/bin/env bash
# Build the Go twinbox CLI to dist/twinbox and optionally install to the user's PATH.
# See AGENTS.md → 协作约束 → Go CLI 变更后的默认构建与安装。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
DIST_DIR="${TWINBOX_GO_DIST_DIR:-$ROOT/dist}"
OUT="${TWINBOX_GO_DIST:-$DIST_DIR/twinbox}"
INSTALL=0
ENSURE_PATH=0
for arg in "$@"; do
	case "$arg" in
		--install) INSTALL=1 ;;
		--ensure-path) ENSURE_PATH=1 ;;
		-h|--help)
			echo "Usage: $0 [--install] [--ensure-path]"
			echo "  Builds cmd/twinbox-go → dist/twinbox (override with TWINBOX_GO_DIST)."
			echo "  --install       Copy binary to TWINBOX_GO_BIN_DEST (default: \$HOME/.local/bin/twinbox)."
			echo "  --ensure-path   If missing, append PATH line to ~/.bashrc (idempotent marker)."
			echo "Env: TWINBOX_GO_INSTALL=1 same as --install; TWINBOX_GO_BIN_DEST, TWINBOX_GO_DIST."
			exit 0
			;;
	esac
done
if [[ "${TWINBOX_GO_INSTALL:-}" == "1" ]]; then
	INSTALL=1
fi
if [[ "${TWINBOX_GO_ENSURE_PATH:-}" == "1" ]]; then
	ENSURE_PATH=1
fi

mkdir -p "$(dirname "$OUT")"
( cd "$ROOT/cmd/twinbox-go" && go build -o "$OUT" . )
echo "built: $OUT"

if [[ "$INSTALL" == "1" ]]; then
	DEST="${TWINBOX_GO_BIN_DEST:-$HOME/.local/bin/twinbox}"
	mkdir -p "$(dirname "$DEST")"
	cp -f "$OUT" "$DEST"
	chmod +x "$DEST"
	echo "installed: $DEST"
fi

if [[ "$ENSURE_PATH" == "1" ]]; then
	BASHRC="${HOME}/.bashrc"
	MARKER="# twinbox scripts/build_go_twinbox.sh: ~/.local/bin on PATH"
	LINE='export PATH="$HOME/.local/bin:$PATH"'
	if [[ -f "$BASHRC" ]] && grep -Fq "$MARKER" "$BASHRC" 2>/dev/null; then
		echo "PATH hint: already present in $BASHRC ($MARKER)"
	elif [[ -f "$BASHRC" ]]; then
		{
			echo ""
			echo "$MARKER"
			echo "$LINE"
		} >>"$BASHRC"
		echo "appended PATH line to $BASHRC (open a new shell or: source ~/.bashrc)"
	else
		echo "warn: $BASHRC not found; add manually: $LINE" >&2
	fi
fi
