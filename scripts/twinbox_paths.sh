#!/usr/bin/env bash
# Shared path resolution for local repo runs and Gastown linked worktrees.

twinbox_config_dir() {
  printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/twinbox"
}

twinbox_canonical_root_file() {
  printf '%s\n' "${TWINBOX_CANONICAL_ROOT_FILE:-$(twinbox_config_dir)/canonical-root}"
}

twinbox_resolve_existing_dir() {
  local candidate="${1:-}"
  if [[ -z "${candidate}" ]]; then
    return 1
  fi
  (
    cd "${candidate}" >/dev/null 2>&1
    pwd -P
  )
}

twinbox_is_linked_worktree() {
  local repo_root="$1"
  local git_dir git_common_dir

  git_dir="$(git -C "${repo_root}" rev-parse --git-dir 2>/dev/null || true)"
  git_common_dir="$(git -C "${repo_root}" rev-parse --git-common-dir 2>/dev/null || true)"

  [[ -n "${git_dir}" && -n "${git_common_dir}" && "${git_dir}" != "${git_common_dir}" ]]
}

twinbox_resolve_canonical_root() {
  local code_root="$1"
  local candidate=""
  local config_file
  local resolved

  if [[ -n "${TWINBOX_CANONICAL_ROOT:-}" ]]; then
    candidate="${TWINBOX_CANONICAL_ROOT}"
  else
    config_file="$(twinbox_canonical_root_file)"
    if [[ -f "${config_file}" ]]; then
      candidate="$(sed -n '1p' "${config_file}")"
    fi
  fi

  if [[ -n "${candidate}" ]]; then
    resolved="$(twinbox_resolve_existing_dir "${candidate}")" || {
      echo "Configured canonical root does not exist: ${candidate}" >&2
      return 1
    }
    printf '%s\n' "${resolved}"
    return 0
  fi

  if twinbox_is_linked_worktree "${code_root}"; then
    echo "Missing canonical root for linked worktree: ${code_root}" >&2
    echo "Run: bash ${code_root}/scripts/register_canonical_root.sh" >&2
    echo "Or set TWINBOX_CANONICAL_ROOT=/abs/path/to/twinbox" >&2
    return 1
  fi

  printf '%s\n' "${code_root}"
}

twinbox_init_roots() {
  local script_path="$1"
  local script_dir code_root canonical_root

  script_dir="$(cd "$(dirname "${script_path}")" && pwd -P)"
  code_root="$(cd "${script_dir}/.." && pwd -P)"
  canonical_root="$(twinbox_resolve_canonical_root "${code_root}")" || return 1

  export TWINBOX_CODE_ROOT="${code_root}"
  export TWINBOX_CANONICAL_ROOT="${canonical_root}"
}
