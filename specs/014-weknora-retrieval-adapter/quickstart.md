# Quickstart — 014
```sh
cd /Users/caapap/iflytek/twinbox
export SPECIFY_FEATURE_DIRECTORY=specs/014-weknora-retrieval-adapter
.specify/scripts/bash/check-prerequisites.sh --json --require-tasks --include-tasks
# 已存在的测试只覆盖默认关闭的 fake-provider 本地合同；不代表真实 API/KB 或邮件材料验收
.venv/bin/python -m pytest tests/test_weknora_sync.py tests/test_weknora_search.py tests/test_weknora_security.py tests/test_weknora_http.py -q
```
开发阶段用fake provider，不需要真实key/KB。测试创建超时→uncertain→对账，不能直接再次create；同scope同摘录skip，变更update，scope冲突拒绝；检索前ACL不能被分类后过滤替代。

真实入库之前必须完成plan L0，并按ops现场版本核对接口。先三十查询对照，再决定启用；不要执行旧008计划中的过期现场写操作。回滚演练关闭新路径、保留sidecar，索引删除另按批准保留策略。
