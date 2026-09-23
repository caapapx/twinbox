# Quickstart — 013

## Select feature (not a git branch)
```sh
cd /Users/caapap/iflytek/twinbox
export SPECIFY_FEATURE_DIRECTORY=specs/013-semantic-policy-projections
.specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
```
读tasks依赖与工作树diff；先执行T001/T002，再按指定切片跑失败测试。不要覆盖select/embedding/accounts现有WIP，不部署或发送邮件。

## Local validation（测试文件按任务拟建）
```sh
.venv/bin/python -m pytest tests/test_semantic_policy.py -q
.venv/bin/python -m pytest tests/test_evidence_contract.py -q
.venv/bin/python -m pytest tests/test_pack.py tests/test_quick_refresh.py tests/test_queue_visibility.py -q
node tests/mcp-autosync.mjs
node tests/mcp-smoke.mjs
```
期望：未知业务类别兼容、未授权/超限/正文拒绝、规则按各type匹配；失败测试修复前应真实红灯。不存在的拟建文件不能当已有测试已跑。

## Frozen local read baseline (T024)

Use the raw classification-snapshot reader as the legacy comparator and the single-case semantic client projection as the candidate: both consume the same `classifications.json` fixture. Do **not** substitute the activity-pulse reader: its payload is a different data contract and the ratio would not be interpretable.

```sh
.venv/bin/python -m pytest tests/test_semantic_store_scale.py -q
.venv/bin/python tests/evaluations/semantic_store_scale.py --counts 5000 20000 --samples 100
```

The probe applies three warm-ups per path, records all 100 post-warm-up samples, and reports nearest-rank p95 plus `new / legacy` p95 ratio. A ratio at or below 1.2 passes only the local synthetic read gate; archive the output beside the execution log and do not turn it into a real-mail, remote-service, or ROI claim.

## Full acceptance
按tasks补齐持久分类/反馈/客户端路径与24案例；性能测量在固定fixture和相同环境，真实金标留私有目录。现场F需明确正式宿主任务入口，weekly读取不等于长程生成。没有入口时记录未验证，不猜任务或推送对象。
