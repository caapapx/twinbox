# Changelog

按时间**倒序**记录项目的重要变更。仓库首提交：**2026-03-16**（当时仓库名为 `email-skill`，后经历 `email-bot` 更名为 **twinbox**）。

---

## 2026-03-24

### Feat

- **Task-facing CLI — action / review**：实现 `ActionCard`、`ReviewItem` 与 **`action suggest` / `action materialize`**、**`review list` / `review show`**（规范中的 `apply`、`approve`、`reject` 等仍为后续能力，以 spec 为准）。

### Refactor

- **docs 目录重构（phase 1）**：建立 `docs/README.md` 作为唯一文档入口；新增 `architecture/`、`roadmap/`、`archive/` 目录骨架与各目录 `README.md`。
- **路径归位**：`docs/architecture.md` 迁至 `docs/ref/architecture.md`；当前路线图迁至 `docs/`；`docs/plans/old/` 迁至 `docs/archive/plans/`；HA 优化机会清单归入 `docs/archive/reports/ha-middleware.md`。

### Docs

- **根入口收敛**：`README.md`、`README.zh.md`、`AGENTS.md`、`CLAUDE.md` 改为指向 `docs/README.md` 与新目录结构，不再继续维护旧 `docs/plans/` 索引。
- **validation 路径保留**：`docs/validation/` 保持不变，仅更新说明文档中的稳定公共入口引用。

---

## 2026-03-23

### Feat

- **Task-facing CLI（核心命令面）**
  - `queue list/show/explain`：从 Phase 4 等工件投影队列视图
  - `context import-material/upsert-fact/profile-set/refresh`：用户上下文管理
  - `thread inspect/explain`：线程状态检视与推理说明（规范中的 `thread summarize` 尚未在 CLI 落地，以 `docs/ref/cli.md` 为准）
  - `digest daily/weekly`：每日/每周摘要视图
  - 统一入口 `scripts/twinbox`，默认支持 `--json` 结构化输出
- **DigestView 与对象契约**：补充 `DigestView` 及 task-facing 对象模型在规范中的完整描述与实现状态更新。
- **遗留脚本整理**：将被 Python core 替代的 phase 脚本迁入 `scripts/old/`；新增 **`docs/ref/scheduling.md`**（通过 SKILL.md 等配置定时任务的集成说明）。

### Refactor

- 计划文档重组：`docs/plans/old/` 收纳历史方案，主目录保持可读。
- `development-progress` 快照更名为 **`docs/CHANGELOG.md`**，作为项目级变更日志入口。

### Docs

- 新增并迭代 **`docs/ref/cli.md`**（命令树、对象模型、实现状态）。
- 清理 **CLAUDE.md**、**AGENTS.md**，压缩常驻上下文。
- **README**：去掉 OpenClaw 表述，强调以线程为中心的路径（read-only → draft → controlled send）。
- **Gog / ClawHub**：gogcli 与 ClawHub Gog skill 分析文档。
- **Phase 4 评测**：可解释性、分层 weekly 评估、评测报告与 baseline 回归门禁（指标如 `urgent_f1`、`pending_f1`、`weekly_action_hit_at_5` 等）。
- **规划类**：HA/持久化中间件优化设想、cadence runtime 策略规范、DigestView 在 object contract 中的实现状态说明。
- 当日开发进度快照（后并入本 CHANGELOG 流程）。

### Tests

- **`python/tests/test_task_cli.py`**：随 CLI 与视图模型扩展，覆盖环境根目录、`DigestView`/工件加载、stale 判断、`ActionCard`/`ReviewItem` 及 action/review 命令路径等（具体用例数以测试文件为准）。

### 小结

Task-facing CLI 从规范到实现落地，并与 Phase 3/4 工件投影对齐；同日完成 Phase 4 评测与文档侧 Gog 分析、README 与代理指引收敛。

---

## 2026-03-20

### Feat

- **Python 核心路径**：搭建 `python` 包与核心模块；Phase 1–4 **thinking** 逐步迁入 Python；Phase 2–3 **loading** 收敛到共享 builder；各 phase **渲染** 收敛到共享 renderer。
- **共享编排契约 CLI**：在编排层暴露与 contract/roots/run 一致的命令面（见 `task_cli` / 编排相关实现）。
- **Canonical state root** 扩展到 Phase 1–3；校准类笔记迁入 runtime 上下文。

### Refactor

- **full-pipeline**：formula 从 convoy 结构改为 **workflow** 结构。
- 重构执行树可视化文档/工件更新。

### Docs

- **验证工件契约**：`docs/ref/validation.md`。
- **语言层优化**与**实现重构计划**更名/迭代（见 `docs/plans/`）。
- **Gastown 集成**：清理 formula fallback 等过时表述。
- **运行与测试路径**：twinbox 本地运行与测试说明（脚本与 Python 测试入口）。

### 小结

bash/公式层与 Python 核心分工清晰化，为后续 task-facing CLI 与评测提供稳定底座。

---

## 2026-03-16 ~ 2026-03-19

### 起源与命名（约 03-16）

- 初始 **email-skill** 脚手架；引用更名为 **email-bot**；增加 Claude-value skill 评估与 README 架构示意图。
- **OpenClaw**：master-only 验证工作流、仓库路径说明（后随 README 策略调整不再作为主叙事）。
- **preflight**：引导式邮箱冒烟脚本。
- **Phase 3（早期文档/模型）**：生命周期建模与示意图；value-realization 自评与模板整理。
- **架构/计划**：渐进式「注意力漏斗」写入计划与 `docs/architecture.md`；公开 V1 runtime 骨架准备。
- **README**：中文优先双语、项目标识改为 **twinbox**、中英文 README 拆分与语气调整。

### LLM 管线与人机上下文（约 03-18 ~ 03-19）

- **Phase 1**：loading / thinking 分层，意图分类由 LLM 完成（含与 regex 对比的迁移报告）。
- **Phase 2**：loading / thinking 分层，人设推断；loading 读取人工事实、习惯与校准笔记。
- **Phase 3**：loading / thinking + 生命周期 LLM 建模，支持 human context。
- **Phase 4**：loading / thinking，日报式价值输出；迁移报告与集成计划更新。
- **LLM 基础设施**：双后端、OpenAI 兼容接口；`max_tokens` 等从环境读取；后端曾切换至 astron-code-latest（见提交历史）。
- **JSON 输出**：加强清理与解析鲁棒性，降低坏 JSON 导致的失败率。

### Gastown 与编排（约 03-19）

- **formula + sling** 全链路融合与操作指南；README 中阶段与 Gastown 管线说明。
- **稳定性**：`phase4_merge` 从并行脚本中拆出，避免重复调用 LLM；polecat worktree 同步、缩小 formula 中 polecat 探索范围；Phase 4 在 Gastown 下 rerun 与 shared root 稳定化；DAG 验证与 shell bootstrap 文档。
- **beads（bd）**：初始化可选 issue 跟踪；显式路由模式；从跟踪中移除应忽略的 `.beads` 元数据。

### Security & 仓库卫生

- **PII**：从 Git 跟踪内容中移除敏感实例数据，改为环境变量等方式注入。
- **.gitignore**：`.beads/`、`.claude/`、`.runtime/` 等本地/agent 目录；处理 stash 合并带来的 `.gitignore` 冲突。

### Docs（跨日）

- 文档目录重组与**多 agent 集成**计划；架构审视（human context 缺口、Gastown 融合路径）；各 Phase LLM 迁移报告（Phase 1–4）；Phase 4 bash 并行 vs Gastown polecat 性能对比；Phase 4 shared-root 清单。

### 小结

从「邮箱 Copilot 脚手架 + 文档」推进到 **四阶段 LLM 分层管线 + Gastown 编排 + Python 核心收敛** 的前一阶段；同步完成 PII/gitignore/beads 治理与验证契约前置文档。

---

## 参考

- 更细的提交列表：`git log --reverse --oneline`
- 架构与阶段定义：`docs/ref/architecture.md`、仓库根 `ROADMAP.md`
- Task 命令规范：`docs/ref/cli.md`
