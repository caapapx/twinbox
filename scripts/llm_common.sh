#!/usr/bin/env bash
# llm_common.sh — 公共 LLM 调用函数，供所有 thinking 脚本 source
# 用法: source scripts/llm_common.sh

_twinbox_python() {
  local code_root script_dir repo_root python_src

  if [[ -n "${TWINBOX_CODE_ROOT:-}" ]]; then
    code_root="${TWINBOX_CODE_ROOT}"
  else
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
    repo_root="$(cd "${script_dir}/.." && pwd -P)"
    code_root="${repo_root}"
  fi

  python_src="${code_root}/python/src"

  if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required for twinbox LLM helpers" >&2
    return 1
  fi

  PYTHONPATH="${python_src}${PYTHONPATH:+:${PYTHONPATH}}" python3 "$@"
}

init_llm_backend() {
  local env_file="${1:-.env}"
  [[ -f "${env_file}" ]] && { set -a; source "${env_file}"; set +a; }
  export TWINBOX_LLM_ENV_FILE="${env_file}"

  _twinbox_python -m twinbox_core.llm backend-summary --env-file "${env_file}"
}

call_llm() {
  local prompt="$1"
  local max_tokens="${2:-4096}"
  local system_prompt="${3:-}"
  local prompt_file system_file
  local -a cmd

  prompt_file="$(mktemp)"
  printf '%s' "${prompt}" > "${prompt_file}"

  cmd=(
    _twinbox_python -m twinbox_core.llm call
    --env-file "${TWINBOX_LLM_ENV_FILE:-}"
    --prompt-file "${prompt_file}"
    --max-tokens "${max_tokens}"
  )

  if [[ -n "${system_prompt}" ]]; then
    system_file="$(mktemp)"
    printf '%s' "${system_prompt}" > "${system_file}"
    cmd+=(--system-prompt-file "${system_file}")
  fi

  "${cmd[@]}"
  local exit_code=$?
  rm -f "${prompt_file}"
  if [[ -n "${system_file:-}" ]]; then
    rm -f "${system_file}"
  fi
  return "${exit_code}"
}

clean_json() {
  _twinbox_python -m twinbox_core.llm clean-json
}
