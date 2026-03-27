# CHANGELOG — tests/

记录测试套件从零到当前状态的完整演进历史。

---

## [Unreleased] — 2026-03-25  测试套件重构

**本轮改动性质**：批判性审查 + 质量补强，不改变被测功能。

### 新增
- `conftest.py` — 共享 pytest fixtures，消除跨文件 setup 重复：
  - `phase4_root`：设置 `TWINBOX_CANONICAL_ROOT` 并创建 `runtime/validation/phase-4/`
  - `write_phase4`：工厂 fixture，一行写入 Phase 4 YAML artifact
  - `sample_urgent_item` / `sample_pending_item` / `sample_sla_item`：带全字段的标准 item
  - `recent_timestamp` / `stale_timestamp`：时间戳测试用例
- `TESTING.md` — 测试策略文档，含目录结构、运行方法、正确性标准、已知设计决策

### 修改

#### `test_task_cli.py` (27 → 44 tests)
| 问题 | 修复方式 |
|------|----------|
| `to_dict()` 只断言字段值，未验证 JSON 可序列化 | 所有数据模型测试改为 `json.dumps()` + `json.loads()` 往返验证 |
| 每个 CLI 测试手动重复 `monkeypatch + mkdir` | 改用 `phase4_root` / `write_phase4` fixtures |
| `_infer_risk_level` 只测中间值，无边界覆盖 | 补充边界：80（high）、79（medium）、50（medium）、49（low） |
| 缺失 `action_hint` key 时行为未测试 | 新增 `test_infer_missing_hint_key_defaults_to_reply` |
| action_hint 大小写处理未测试 | 新增 `test_infer_action_type_is_case_insensitive` |
| `_is_stale` 未测试畸形 / None 输入 | 新增 `test_malformed_timestamp_treated_as_stale`、`test_none_timestamp_treated_as_stale` |
| `_load_yaml_artifact` 未测试格式错误 YAML | 新增 `test_load_malformed_yaml_returns_empty_dict`（同时暴露源码缺少 try/except 的 bug） |
| `action suggest` 空队列不验证 JSON 结构 | 改用 `capsys`，断言输出为空列表 `[]` |
| `review list` 未测试 missing explainability 路径 | 新增 `test_review_list_flags_missing_explainability` |
| CLI 输出未做 contract 字段校验 | 新增 `test_action_suggest_json_output_contract`、`test_review_list_json_contract`、`test_thread_inspect_found_returns_full_contract` |
| `urgency_score=0` 注释声称触发 confidence_check，实为误导 | 改用 `urgency_score=30`，正确覆盖 confidence_check 路径；注释修正 |

#### `test_llm.py` (2 → 7 tests)
| 问题 | 修复方式 |
|------|----------|
| `clean_json_text` 只断言子串存在，从未验证输出是合法 JSON | 新增 `_assert_valid_json()` helper，所有用例均调用 `json.loads()` |
| 缺乏场景覆盖 | 新增：已有效 JSON 直通、无 fence、嵌套 trailing comma、数组根节点 |
| `unittest.TestCase` 混用风格 | 迁移至 pytest class 风格 |

#### `test_evaluation.py` (4 → 11 tests)
| 问题 | 修复方式 |
|------|----------|
| 缺少完美匹配（F1=1.0）和零重合（F1=0.0）边界 | 新增 `test_perfect_match_gives_f1_of_1`、`test_zero_overlap_gives_f1_of_0` |
| 缺少空 predicted / 空 expected 用例 | 新增 `test_empty_predicted_gives_f1_of_0`、`test_empty_expected_gives_f1_of_0` |
| 空集合 F1 = 1.0 的设计意图无文档 | 新增 `test_both_empty_gives_f1_of_1`，带注释说明 `_safe_ratio(0,0)=1.0` 语义 |
| gate passes 路径（正向）未测 | 新增 `test_gate_passes_when_no_regression` |
| report 字段完整性未测 | 新增 `test_report_always_includes_required_fields` |
| `tempfile.TemporaryDirectory` 手动管理 | 改用 pytest `tmp_path` fixture |

### 源码修复（因测试暴露）
- `task_cli.py::_load_yaml_artifact` — 补加 `try/except Exception`，防止 Phase 4 产出不完整 YAML 时 CLI crash

### 测试总数变化
```
重构前：27 (test_task_cli) + 4 (evaluation) + 2 (llm) = 33 核心测试
重构后：95 passed
  test_task_cli.py   27 → 52 tests
  test_evaluation.py  4 → 16 tests
  test_llm.py         2 →  7 tests
  其余文件不变       +20 tests
```

---

## [0.5.0] — 2026-03-24  ActionCard / ReviewItem / action+review 命令

**对应 commit**: `327f737`

- `test_task_cli.py` +234 行，累计 27 tests
- 新增 `TestActionCard`（9 tests）：`to_dict()`、`_infer_action_type`（reply/forward/archive/default）、`_infer_risk_level`（high/medium/low）
- 新增 `TestReviewItem`（1 test）：`to_dict()`
- 新增 `TestActionCommands`（4 tests）：空队列、从 urgent 投影 action、materialize 未找到、materialize 成功
- 新增 `TestReviewCommands`（3 tests）：空列表、低置信度标记、show 未找到

---

## [0.4.1] — 2026-03-23  DigestView 对象与 contract 规范

**对应 commit**: `99301a0`

- `test_task_cli.py` +59 行，累计 8 tests
- 新增 `TestDigestView`（2 tests）：daily 序列化、weekly 三段结构（action_now / backlog / important_changes）

---

## [0.4.0] — 2026-03-23  task-facing CLI 首批测试

**对应 commit**: `23a8903`

- 新建 `test_task_cli.py`，115 行，6 tests
- 覆盖 `TestPhase4DirResolution`（2 tests）：env var 优先、fallback to cwd
- 覆盖 `TestThreadCard`（1 test）：`to_dict()` 字段
- 覆盖 `TestQueueView`（1 test）：`to_dict()` + items count
- 覆盖 `TestHelperFunctions`（4 tests）：missing file、valid YAML、stale 判断

---

## [0.3.1] — 2026-03-23  Phase 4 explainability 与分层 weekly 评测

**对应 commit**: `a68f581`

- `test_evaluation.py` +72 行，累计 4 tests
- 新增 `test_evaluate_phase4_uses_layered_weekly_action_now`：action_now 优先于 top_actions
- 新增 `test_cli_gate_fails_on_explainability_floor`：`--min-explainability 1.0` 门禁

---

## [0.3.0] — 2026-03-23  Phase 4 评测基线回归门禁

**对应 commit**: `36f25c2`

- 新建 `test_evaluation.py`，87 行，2 tests
- 覆盖 F1 metrics 计算（urgent/pending/weekly）
- 覆盖 CLI gate：baseline 回退超阈值时 exit 1

---

## [0.2.5] — 2026-03-20  Orchestration contract 测试

**对应 commit**: `23e176b`

- 新建 `test_orchestration.py`，63 行
- 覆盖 contract payload 结构、phase4 并行/串行 step 配置、dry-run 输出

---

## [0.2.4] — 2026-03-20  共享 renderer 测试

**对应 commit**: `aa09528`

- 新建 `test_renderer.py`，76 行
- 覆盖 Phase 2/3/4 YAML 输出、mermaid 图表生成（子串断言）

---

## [0.2.3] — 2026-03-20  context_builder 测试

**对应 commit**: `cb2da61`

- 新建 `test_context_builder.py`，107 行
- 覆盖 Phase 2 enriched_samples 构建、Phase 3 context 加载路径

---

## [0.2.2] — 2026-03-20  Phase 2-4 thinking 测试

**对应 commit**: `c7fa4ef`

- 新建 `test_phase2_persona.py`（80 行）：persona hypothesis 生成，含 LLM mock
- 新建 `test_phase3_lifecycle.py`（90 行）：lifecycle flow 生成，含 LLM mock
- 新建 `test_phase4_value.py`（85 行）：Phase 4 merge 输出验证

---

## [0.2.1] — 2026-03-20  Phase 1 thinking + LLM boundary 测试

**对应 commit**: `b1c83ef`

- 新建 `test_llm.py`（42 行）：`resolve_backend` 配置、`clean_json_text` 修复（子串断言）
- 新建 `test_phase1_intent.py`（68 行）：干运行输出文件存在性验证

---

## [0.1.0] — 2026-03-20  测试套件初始化

**对应 commit**: `c5110c2`

- 新建 `test_paths.py`（104 行），测试套件首个文件
- 覆盖路径解析、env var 优先级、worktree 检测、config 文件读取

---

## 附：当前工作树未提交文件

| 文件 | 说明 |
|------|------|
| `conftest.py` | 新增：共享 pytest fixtures |
| `TESTING.md` | 新增：测试策略文档 |
| `CHANGELOG.md` | 新增：本文件 |
| `test_task_cli.py` | 修改：重构（见 [Unreleased] 区块） |
| `test_llm.py` | 修改：重构（见 [Unreleased] 区块） |
| `test_evaluation.py` | 修改：重构（见 [Unreleased] 区块） |
| `fixtures/delivery_director_ops/` 等 | 已移除；信封探针测试改为内联样本 |
