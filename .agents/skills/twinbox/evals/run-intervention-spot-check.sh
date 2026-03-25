#!/usr/bin/env bash
# 人工干预单点验证：追加 calibration 夹具 → 可选重跑 Phase 4 → 抓取 digest/action 供 diff。
# 在仓库根执行：
#   bash .claude/skills/twinbox/evals/run-intervention-spot-check.sh help
# 追加夹具后重算（需本机 LLM / 邮箱管线）：
#   TWINBOX_INTERVENTION_RUN_PHASE4=1 bash .../run-intervention-spot-check.sh case1
#
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
EVAL_DIR="$(cd "$(dirname "$0")" && pwd)"
CAL="${REPO_ROOT}/runtime/context/instance-calibration-notes.md"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="${REPO_ROOT}/runtime/context/.intervention-backups"

usage() {
  cat <<'USAGE'
用法: run-intervention-spot-check.sh <command>

  help          显示说明与评测 JSON 路径
  case1         备份 calibration 并追加「周台账」合成夹具（IV-1）
  case2         备份 calibration 并追加「交付支持角色」合成夹具（IV-2）
  capture       将当前 digest weekly / action suggest 打到 /tmp（不落库）
  restore-last  从最近一次备份恢复 instance-calibration-notes.md

环境变量:
  TWINBOX_INTERVENTION_RUN_PHASE4=1   在 case1/case2 追加后执行 twinbox-orchestrate run --phase 4

说明:
  import-material 对 csv/xlsx/docx/pptx 会生成 .extracted.md 并由 Phase4 注入 human_context；
  角色长文仍可追加 calibration。详见 intervention-spot-check-2026-03-24.json。
USAGE
}

ensure_repo() {
  if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]]; then
    echo "错误：未找到仓库根 pyproject.toml：${REPO_ROOT}" >&2
    exit 1
  fi
}

append_block() {
  local tag="$1"
  local fixture="$2"
  mkdir -p "${REPO_ROOT}/runtime/context" "${BACKUP_DIR}"
  if [[ -f "${CAL}" ]]; then
    cp -a "${CAL}" "${BACKUP_DIR}/instance-calibration-notes.md.${STAMP}.bak"
    echo "已备份: ${BACKUP_DIR}/instance-calibration-notes.md.${STAMP}.bak"
  else
    touch "${CAL}"
  fi
  {
    echo ""
    echo "<!-- intervention-spot-check ${tag} ${STAMP} -->"
    cat "${fixture}"
    echo ""
  } >>"${CAL}"
  echo "已追加到: ${CAL}"
}

cmd="${1:-help}"
cd "${REPO_ROOT}"
ensure_repo

case "${cmd}" in
  help|-h|--help)
    usage
    echo ""
    echo "评测定义: ${EVAL_DIR}/intervention-spot-check-2026-03-24.json"
    ;;
  case1)
    append_block "IV-1" "${EVAL_DIR}/fixtures/synthetic/weekly-deployment-ledger-sample.md"
    if [[ "${TWINBOX_INTERVENTION_RUN_PHASE4:-}" == "1" ]]; then
      twinbox-orchestrate run --phase 4
    else
      echo "未设置 TWINBOX_INTERVENTION_RUN_PHASE4=1，跳过 Phase 4。请手动: twinbox-orchestrate run --phase 4"
    fi
    ;;
  case2)
    append_block "IV-2" "${EVAL_DIR}/fixtures/synthetic/persona-delivery-support-calibration-snippet.md"
    if [[ "${TWINBOX_INTERVENTION_RUN_PHASE4:-}" == "1" ]]; then
      twinbox-orchestrate run --phase 4
    else
      echo "未设置 TWINBOX_INTERVENTION_RUN_PHASE4=1，跳过 Phase 4。请手动: twinbox-orchestrate run --phase 4"
    fi
    ;;
  capture)
    mkdir -p /tmp/twinbox-intervention-capture
    twinbox digest weekly --json >"/tmp/twinbox-intervention-capture/weekly-${STAMP}.json"
    twinbox action suggest --json >"/tmp/twinbox-intervention-capture/suggest-${STAMP}.json"
    echo "已写入 /tmp/twinbox-intervention-capture/weekly-${STAMP}.json"
    echo "已写入 /tmp/twinbox-intervention-capture/suggest-${STAMP}.json"
    ;;
  restore-last)
    latest=$(ls -1t "${BACKUP_DIR}"/instance-calibration-notes.md.*.bak 2>/dev/null | head -1)
    if [[ -z "${latest}" ]]; then
      echo "无备份可恢复" >&2
      exit 1
    fi
    cp -a "${latest}" "${CAL}"
    echo "已从 ${latest} 恢复 ${CAL}"
    ;;
  *)
    echo "未知命令: ${cmd}" >&2
    usage
    exit 1
    ;;
esac
