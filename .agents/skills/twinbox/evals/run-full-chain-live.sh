#!/usr/bin/env bash
# 只读全链路 live 跑法；中文用户场景文案来自同目录 full-chain-2026-03-24.json（live_steps.user_prompt_zh）。
# 在仓库根执行：
#   bash .claude/skills/twinbox/evals/run-full-chain-live.sh
# 可选：TWINBOX_EVAL_SKIP_ORCHESTRATE=1 跳过 phase4。

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/../../../.." && pwd)
EVAL_JSON="$(cd "$(dirname "$0")" && pwd)/full-chain-2026-03-24.json"
cd "$REPO_ROOT"

if [[ ! -f "$EVAL_JSON" ]]; then
  echo "错误：找不到测试集 JSON：$EVAL_JSON" >&2
  exit 1
fi

json_ok() {
  python3 -c "import json,sys; json.load(sys.stdin)" >/dev/null 2>&1
}

user_prompt_zh() {
  python3 -c "
import json, sys
path, step = sys.argv[1], int(sys.argv[2])
with open(path, encoding='utf-8') as f:
    d = json.load(f)
for s in d['live_steps']:
    if s['step'] == step:
        print(s.get('user_prompt_zh', ''))
        break
" "$EVAL_JSON" "$1"
}

run_json_step() {
  local step="$1"
  local name="$2"
  shift 2
  echo ""
  echo "========== 步骤 ${step}：${name} =========="
  echo "【用户提问】$(user_prompt_zh "$step")"
  echo "【命令】$*"
  local out ec=0
  out=$("$@" 2>&1) || ec=$?
  if [[ "$ec" -ne 0 ]]; then
    echo "$out"
    echo "失败：${name}（退出码 ${ec}）"
    return 1
  fi
  if ! echo "$out" | json_ok; then
    echo "$out"
    echo "失败：${name}（标准输出不是合法 JSON）"
    return 1
  fi
  echo "成功：${name}"
  echo "$out"
}

echo "仓库：$REPO_ROOT"
echo "测试集：$EVAL_JSON"
echo "日期标记：full-chain-2026-03-24"

echo ""
echo "========== 步骤 1：mailbox preflight =========="
echo "【用户提问】$(user_prompt_zh 1)"
echo "【命令】twinbox mailbox preflight --json"
set +e
PREFLIGHT_OUT=$(twinbox mailbox preflight --json 2>&1)
PREFLIGHT_EC=$?
set -e
echo "$PREFLIGHT_OUT"
if [[ "$PREFLIGHT_EC" -ne 0 ]]; then
  echo "警告：预检退出码 ${PREFLIGHT_EC} — 继续执行；队列/摘要可能为空或 stale。"
else
  echo "$PREFLIGHT_OUT" | json_ok || { echo "失败：预检标准输出不是合法 JSON"; exit 1; }
  echo "成功：preflight（json）"
fi

echo ""
echo "========== 步骤 2：orchestrate phase4（可选）=========="
echo "【用户提问】$(user_prompt_zh 2)"
if [[ "${TWINBOX_EVAL_SKIP_ORCHESTRATE:-}" != "1" ]]; then
  echo "【命令】twinbox-orchestrate run --phase 4"
  twinbox-orchestrate run --phase 4
  echo "成功：orchestrate phase4"
else
  echo "【跳过】已设置 TWINBOX_EVAL_SKIP_ORCHESTRATE=1"
fi

run_json_step 3 "queue list" twinbox queue list --json

run_json_step 4 "queue show urgent" twinbox queue show urgent --json
run_json_step 5 "queue show pending" twinbox queue show pending --json
run_json_step 6 "queue show sla_risk" twinbox queue show sla_risk --json

TID=$(twinbox queue show urgent --json | python3 -c "import json,sys; d=json.load(sys.stdin); print((d.get('items')or[{}])[0].get('thread_id')or'')")
if [[ -n "$TID" ]]; then
  run_json_step 7 "thread inspect" twinbox thread inspect "$TID" --json
  run_json_step 8 "thread explain" twinbox thread explain "$TID" --json
else
  echo ""
  echo "跳过：thread inspect/explain（紧急队列为空，无 thread_id）"
fi

run_json_step 9 "digest daily" twinbox digest daily --json
run_json_step 10 "digest weekly" twinbox digest weekly --json

AS_OUT=$(twinbox action suggest --json) || true
echo ""
echo "========== 步骤 11：action suggest =========="
echo "【用户提问】$(user_prompt_zh 11)"
echo "【命令】twinbox action suggest --json"
if echo "$AS_OUT" | json_ok; then
  echo "成功：action suggest"
  echo "$AS_OUT"
  ACT=$(echo "$AS_OUT" | python3 -c "import json,sys; a=json.load(sys.stdin); print(a[0]['action_id'] if isinstance(a,list)and a else '')")
  if [[ -n "$ACT" ]]; then
    run_json_step 12 "action materialize" twinbox action materialize "$ACT" --json
  else
    echo "跳过：action materialize（建议列表为空）"
  fi
else
  echo "失败：action suggest 标准输出不是合法 JSON"
  exit 1
fi

RL_OUT=$(twinbox review list --json) || true
echo ""
echo "========== 步骤 13：review list =========="
echo "【用户提问】$(user_prompt_zh 13)"
echo "【命令】twinbox review list --json"
if echo "$RL_OUT" | json_ok; then
  echo "成功：review list"
  echo "$RL_OUT"
  RID=$(echo "$RL_OUT" | python3 -c "import json,sys; a=json.load(sys.stdin); print(a[0]['review_id'] if isinstance(a,list)and a else '')")
  if [[ -n "$RID" ]]; then
    run_json_step 14 "review show" twinbox review show "$RID" --json
  else
    echo "跳过：review show（审核列表为空）"
  fi
else
  echo "失败：review list 标准输出不是合法 JSON"
  exit 1
fi

echo ""
echo "========== 步骤 15：queue explain =========="
echo "【用户提问】$(user_prompt_zh 15)"
echo "【命令】twinbox queue explain"
twinbox queue explain
echo "成功：全链路 live 跑完"
