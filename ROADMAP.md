# twinbox 路线与待办（ROADMAP）

**最后更新：** 2026-03-29（发布前手动验收整理）  

本文档**取代**仓库内已删除的分散计划稿：`skill-creator-plan.md`、`.cursor/plans/prompt_and_code_optimization_*.plan.md`、`docs/superpowers/plans/*`、`docs/superpowers/specs/*`（增量邮件设计）、`docs/core-refactor-v1.md`，以及空的 `docs/core-refactor-v2-latest.md` 占位。  

**当前实现事实**（daemon、Go 薄壳、vendor、模组化模拟邮箱、**phase1/4 取信仍经 himalaya CLI**）：[`docs/ref/daemon-and-runtime-slice.md`](docs/ref/daemon-and-runtime-slice.md)。**架构：** [`docs/ref/architecture.md`](docs/ref/architecture.md)。**CLI：** [`docs/ref/cli.md`](docs/ref/cli.md)。**OpenClaw 宿主：** [`openclaw-skill/DEPLOY.md`](openclaw-skill/DEPLOY.md)。**简版已交付清单：** 根目录 [README.md](README.md) / [README.zh.md](README.zh.md)「当前聚焦」— 与本文冲突时**以本文为准**。

**当前状态**：runtime / deploy / onboard 这一轮实现已基本收口；当前重点从“继续堆功能”切到“完整手动验收 + 准备发布”。

---

## 合并进本路线的来源

| 原文件 | 作用 |
|--------|------|
| `skill-creator-plan.md` | Track A（本地 agent）vs Track B（OpenClaw）分包、验证阶梯、平台缺口 |
| `.cursor/plans/prompt_and_code_optimization_*.plan.md` | Phase 2–4 prompt 架构 + Phase 4 正确性（loading、`recipient_role`、`--dry-run`、calibration） |
| `docs/superpowers/plans/2026-03-26-incremental-mail-processing-implementation.md` | UID watermark、`daytime-sync`、merge context、queue state、orchestration 接线 |
| `docs/core-refactor-v1.md` | 分阶段核心重构（paths → LLM boundary → context → skill surface → Go 再评估）+ 原 TODO-1…4 |
| `dev-go` 上近期 `git log`（约 80 条） | Onboarding v2、单一 `twinbox.json`、OpenClaw deploy 拆分、daemon/RPC、vendor、tests |
| Cursor `twinbox_runtime_daemon_vendor_merged.plan.md`（本机 `.cursor/plans/`，可选） | 运行时切片叙事：daemon/vendor/deploy、**纯 Python mail transport** 等待办、Go 单一入口等；**以仓库内 `daemon-and-runtime-slice.md` + 本文为准** |

---

## 已完成（树内可核对或计划已结案）

### 提交主题（2026-03）

- **Phase 4 / prompts：** loading 修复、`recipient_role` 打分与展示分离、真实的 `--dry-run`、calibration 与 onboarding notes 进 context（`024ea99` 及相关）。
- **Onboarding / config：** OpenClaw journey shell、从 OpenClaw 导入 LLM、单一配置源、TTY/journey 与 secret 遮罩。
- **OpenClaw deploy：** 分步模块、JSON merge 辅助、deploy 测试、捆绑 Himalaya、state root 下 canonical `SKILL.md`、链到 OpenClaw skills 目录的 symlink。
- **Runtime：** JSON-RPC daemon + 协议测试、`--supervise` 自动拉起、可注入的 `cli_invoke` CLI runner、`twinbox vendor install|status|integrity`、`twinbox install --archive`（本地/HTTP）、用户交付命令默认名为 `twinbox`、`--profile` + `TWINBOX_HOME` 共享 vendor。
- **Orchestration：** Phase 1/4 loading 编排进 Python；`task_cli` lazy import 以加快 daemon 子进程。
- **增量邮件（计划结案）：** `imap_incremental`、`merge_context`、`user_queue_state`、`daytime-sync` 路径、queue dismiss/complete/restore + tests — 按 2026-03-26 实施计划状态。
- **运行时验证入口：** `scripts/verify_runtime_slice.sh` 已覆盖 daemon / vendor / loading / OpenClaw deploy / Go entrypoint 的仓库内回归检查。

### Cursor 计划：prompt + 代码优化

计划 frontmatter 中已全部标为 **completed**：Phase 4 `onboarding_profile_notes` loading、`recipient_role` 修复、`skip_phase4` 过滤后的 dry-run、`instance-calibration-notes.md` 桥接、`prompt_fragments` + Phase 2/3/4 的 system/user 划分、tests + SKILL 更新（合入 `024ea99`）。

### 核心重构（高层）

- **Paths / roots：** Python `paths.py`，`~/.config/twinbox/` 下指针文件，见 [`docs/ref/code-root-developer.md`](docs/ref/code-root-developer.md)。
- **Orchestration contract：** `twinbox_core.orchestration` 为共享契约 + `twinbox-orchestrate` 入口。
- **Loading：** Phase 2/3 context 构建与大量 loading 逻辑已在 Python（新工作不再堆 shell 重复实现）。
- **LLM 模块：** 已有 `src/twinbox_core/llm.py`；「所有 phase thinking 走单一 boundary」仍是渐进目标（见 backlog）。
- **Daemon + Go thin client + vendor：** 已交付；见 daemon slice 文档。

---

## 未完成 / 开放 backlog

按执行优先级分组；与 README「当前聚焦」重叠处以此文为准。

### 当前发布门槛（优先于长期 backlog）

| 项 | 说明 |
|----|------|
| **OpenClaw 宿主全流程手测** | 从干净宿主按 `twinbox onboard openclaw --json` 走完：门槛检查、roots、SKILL 同步、Gateway 重启、交接到 `twinbox onboarding …`。 |
| **宿主脚本化替代路径** | `twinbox deploy openclaw --json`、`--rollback --json`、升级后再次 deploy 的手测闭环。 |
| **vendor / no-clone 交付路径** | 用 `twinbox install --archive …` 或 `twinbox vendor install` 验证无完整仓库 checkout 时仍可运行。 |
| **daemon / CLI 真实宿主烟测** | `twinbox daemon start --supervise`、`status --json`、`stop`，以及 `twinbox task todo --json` / `weekly --json` 的宿主实测。 |
| **平台真实行为核实** | 若本轮要对外承诺 OpenClaw 自动能力，需在真实版本核实 `preflightCommand` 与 `metadata.openclaw.schedules` 的实际消费方式。 |

### 发布后 backlog（非本轮上线阻塞）

### P0 — 产品契约

| 项 | 说明 |
|----|------|
| **`context_updated` → 真实重跑** | 在 `context import-material` / `upsert-fact` / 画像更新后发 marker 或事件；`context refresh` 应触发 Phase 1（或范围重跑），不能只做提示。（原 TODO-2） |
| **Review / action CLI** | `twinbox review approve|reject`、`twinbox action apply` 且需显式确认。（原 TODO-3） |
| **Skill 呈现 vs phase 术语** | Task-facing CLI 已较宽；根 `SKILL.md` 应保持薄，主路径不必让读者理解 phase 编号。（原 TODO-1 余量） |

### P1 — OpenClaw / Track B（平台 + 宿主）

| 项 | 说明 |
|----|------|
| **`preflightCommand` 自动执行** | 核实 OpenClaw 是否自动跑；文档化真实行为。 |
| **`metadata.openclaw.schedules`** | 在平台 import 未证实前视为声明层；对照真实 cron / system-event 验证。 |
| **`twinbox` agent 会话隔离** | 减少 `agent:twinbox:main` 复用 / 空 `assistant`；与「skill/env 变更后新开 session」一致。 |
| **宿主加固** | 生产级 service 安装、retry、告警、**stale-artifact fallback** 责任边界（与 P3「运行时归档快照」互补：前者偏运行中恢复，后者偏历史保留）。 |
| **Subscription registry** | 多渠道投递，不依赖临时 session history。 |
| **Track A 打磨** | `.claude/skills/twinbox` 与根 `SKILL.md` 边界、references 深度、与 hosted smoke 的 eval 对齐。 |

### P2 — 工程质量

| 项 | 说明 |
|----|------|
| **统一 LLM boundary** | 各 phase thinking 路径集中处理 provider 差异、retry、timeout、JSON repair（超出当前 `llm.py` 覆盖面）。 |
| **Render / merge 去重** | merge-only 与并行 Phase 4 路径仍分叉处减少重复。 |
| **Attention-budget 驱动依赖** | 以 `attention-budget.yaml` 作 phase gate 的测试加强，而非仅「文件存在」。 |
| **Eval / baseline** | `twinbox-eval-phase4` 与 baseline：仓库策略为**本地 `pytest`**（树内无 GitHub Actions workflow）；是否接外部 CI 由宿主决定。（原 TODO-4，已改述） |

### P3 — 自动化（闸门到位前 Phase 1–4 仍只读）

| 项 | 说明 |
|----|------|
| **Draft + approval** | 显式闸门后；Phase 1–4 保持 read-only。 |
| **结构化 audit trail** | 如 README 所述 `runtime/audit/` 叙事。 |
| **Action template registry + review UI/CLI** | 文档侧 contract 已有；产品面仍开放。 |
| **Runtime archive snapshots** | 夜间/每周/失败时的产物快照。 |
| **Fully local LLM** | 可选部署模式；不阻塞 OpenAI-compatible 托管路径。 |

---

## 增量邮件设计说明

UID watermark + user queue state 的**设计稿**原在 `docs/superpowers/specs/`（随合并已删）；行为**已实现**（见上文「已完成」）。若需旧叙事可从 git history 恢复。

---

## 如何维护本文

- 每个**可交付**切片落地后，将对应条从 **未完成** 挪到 **已完成**（或删除），必要时补一行 merge commit 指针。
- 深度设计优先链到 **参考文档**；本文保持为**单一 backlog 索引**。
- 根 **README** / **README.zh** 中「当前聚焦 / 待办摘要」应与本文 **P0–P3 同步**（日期行 + 归类）；**长表只维护在本文**，README 仅保留短列表。
- 发布窗口内，优先维护「当前发布门槛」；只有确认不阻塞上线的事项才放回 P0–P3 长期 backlog。
