#!/usr/bin/env bash
# Shared path resolution for twinbox.

_twinbox_paths_py() {
  local script_dir repo_root python_src

  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  repo_root="$(cd "${script_dir}/.." && pwd -P)"
  python_src="${repo_root}/src"

  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required for twinbox path resolution" >&2
    return 1
  fi

  PYTHONPATH="${python_src}${PYTHONPATH:+:${PYTHONPATH}}" python3 -m twinbox_core.paths "$@"
}

twinbox_config_dir() {
  _twinbox_paths_py config-dir
}

twinbox_canonical_root_file() {
  _twinbox_paths_py canonical-root-file
}

twinbox_state_root_file() {
  _twinbox_paths_py state-root-file
}

twinbox_code_root_file() {
  _twinbox_paths_py code-root-file
}

twinbox_resolve_existing_dir() {
  _twinbox_paths_py resolve-existing-dir "${1:-}"
}

twinbox_resolve_code_root() {
  _twinbox_paths_py resolve-code-root "$1"
}

twinbox_resolve_state_root() {
  _twinbox_paths_py resolve-state-root "$1"
}

twinbox_resolve_canonical_root() {
  _twinbox_paths_py resolve-canonical-root "$1"
}

twinbox_init_roots() {
  local script_path="$1"
  local roots=()

  mapfile -t roots < <(_twinbox_paths_py init-roots "${script_path}") || return 1
  [[ "${#roots[@]}" -eq 2 ]] || {
    echo "Expected two root values from twinbox_core.paths" >&2
    return 1
  }

  export TWINBOX_CODE_ROOT="${roots[0]}"
  export TWINBOX_STATE_ROOT="${roots[1]}"
  export TWINBOX_CANONICAL_ROOT="${TWINBOX_CANONICAL_ROOT:-${TWINBOX_STATE_ROOT}}"
}
