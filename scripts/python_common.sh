#!/usr/bin/env bash
# Shared helper for invoking the twinbox Python core.

_twinbox_python() {
  local code_root script_dir repo_root python_src

  if [[ -n "${TWINBOX_CODE_ROOT:-}" ]]; then
    code_root="${TWINBOX_CODE_ROOT}"
  else
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
    repo_root="$(cd "${script_dir}/.." && pwd -P)"
    code_root="${repo_root}"
  fi

  python_src="${code_root}/src"

  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required for twinbox Python helpers" >&2
    return 1
  fi

  PYTHONPATH="${python_src}${PYTHONPATH:+:${PYTHONPATH}}" python3 "$@"
}
