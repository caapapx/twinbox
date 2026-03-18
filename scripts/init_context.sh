#!/usr/bin/env bash
# Initialize runtime/context/ directory with empty templates.
# Safe to run multiple times — only creates files that don't exist.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CTX="${ROOT_DIR}/runtime/context"

mkdir -p "${CTX}/material-extracts"

create_if_missing() {
  local file="$1" content="$2"
  if [[ ! -f "${file}" ]]; then
    echo "${content}" > "${file}"
    echo "  created: ${file}"
  fi
}

create_if_missing "${CTX}/manual-facts.yaml" \
'# manual-facts.yaml — 人工确认事实（owner、术语、发件人纠偏等）
# 证据标签：user_confirmed_fact | user_declared_rule | material_evidence
facts: []'

create_if_missing "${CTX}/manual-habits.yaml" \
'# manual-habits.yaml — 工作习惯与周期任务
# 证据标签：user_declared_rule
habits: []'

create_if_missing "${CTX}/material-manifest.json" \
'{"generated_at":"","materials":[]}'

echo "runtime/context/ initialized."
