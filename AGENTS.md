# AGENTS.md

## 文档索引规则

| 目录 | 用途 | 命名规则 |
|------|------|----------|
| docs/plans/ | 方案、路线图、集成计划 | `<topic>.md` |
| docs/specs/ | 技术规范、合约定义 | `<component>-<aspect>.md` |
| docs/reports/ | 评估报告、质量审计 | `<subject>-evaluation.md` |
| docs/templates/ | 可复用模板 | `<name>-template.md` |
| docs/validation/ | 实例级验证报告（本地数据，不入公开发布） | `phase-N-report.md` |
| docs/assets/ | 图片、静态资源 | 按需 |

## 核心文档入口

- 架构：`docs/architecture.md`
- 渐进验证框架：`docs/plans/progressive-validation-framework.md`
- 验证工件契约：`docs/specs/validation-artifact-contract.md`
- 多 agent 集成：`docs/plans/gastown-multi-agent-integration.md`
- 运行时规范：`docs/specs/thread-state-runtime.md`
- 开源 V1 计划：`docs/plans/open-source-v1-plan.md`
- Phase 1 intent LLM 改造记录：`docs/reports/phase1-intent-llm-migration.md`
- Phase 2 persona LLM 改造记录：`docs/reports/phase2-persona-llm-migration.md`
- Phase 3 前架构审视：`docs/reports/architecture-review-before-phase3.md`
- Phase 3 lifecycle LLM 改造记录：`docs/reports/phase3-lifecycle-llm-migration.md`
- Phase 4 value LLM 改造记录：`docs/reports/phase4-value-llm-migration.md`

## Gastown Formula

项目 formula 定义在 `.beads/formulas/`，gastown 会自动搜索此路径。

| Formula | 类型 | 用途 |
|---------|------|------|
| `twinbox-phase1` | workflow | Phase 1 loading → thinking (intent) |
| `twinbox-phase2` | workflow | Phase 2 loading → thinking (persona) |
| `twinbox-phase3` | workflow | Phase 3 loading → thinking (lifecycle) |
| `twinbox-phase4` | workflow | Phase 4 loading → thinking (value) |
| `twinbox-full-pipeline` | convoy | 4 Phase 全流程 + synthesis |

Fallback 编排：`scripts/run_pipeline.sh`（纯 bash 串行，不依赖 gastown）。

## Agent 角色（gastown 集成后）

| 角色 | gastown 映射 | 职责 |
|------|-------------|------|
| Analyst | Polecat × N | Phase 1-3 子任务执行 |
| Value | Polecat × N | Phase 4 子任务执行 |
| Merger | Refinery | 合并子任务输出为 attention-budget.yaml |
| Monitor | Witness | 监控 polecat 健康、崩溃恢复 |

## 协作约束

1. 所有方案类文档放 docs/plans/，不在 docs/ 根目录散放
2. 新增文档前先检查是否有可合并的已有文档
3. validation/ 下的内容是实例数据，不应被方案文档引用为"事实"
4. 文档内交叉引用使用相对路径

<!-- BEGIN BEADS INTEGRATION v:1 profile:full hash:d4f96305 -->
## Issue Tracking with bd (beads)

**IMPORTANT**: This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

### Why bd?

- Dependency-aware: Track blockers and relationships between issues
- Git-friendly: Dolt-powered version control with native sync
- Agent-optimized: JSON output, ready work detection, discovered-from links
- Prevents duplicate tracking systems and confusion

### Quick Start

**Check for ready work:**

```bash
bd ready --json
```

**Create new issues:**

```bash
bd create "Issue title" --description="Detailed context" -t bug|feature|task -p 0-4 --json
bd create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:bd-123 --json
```

**Claim and update:**

```bash
bd update <id> --claim --json
bd update bd-42 --priority 1 --json
```

**Complete work:**

```bash
bd close bd-42 --reason "Completed" --json
```

### Issue Types

- `bug` - Something broken
- `feature` - New functionality
- `task` - Work item (tests, docs, refactoring)
- `epic` - Large feature with subtasks
- `chore` - Maintenance (dependencies, tooling)

### Priorities

- `0` - Critical (security, data loss, broken builds)
- `1` - High (major features, important bugs)
- `2` - Medium (default, nice-to-have)
- `3` - Low (polish, optimization)
- `4` - Backlog (future ideas)

### Workflow for AI Agents

1. **Check ready work**: `bd ready` shows unblocked issues
2. **Claim your task atomically**: `bd update <id> --claim`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue:
   - `bd create "Found bug" --description="Details about what was found" -p 1 --deps discovered-from:<parent-id>`
5. **Complete**: `bd close <id> --reason "Done"`

### Auto-Sync

bd automatically syncs via Dolt:

- Each write auto-commits to Dolt history
- Use `bd dolt push`/`bd dolt pull` for remote sync
- No manual export/import needed!

### Important Rules

- ✅ Use bd for ALL task tracking
- ✅ Always use `--json` flag for programmatic use
- ✅ Link discovered work with `discovered-from` dependencies
- ✅ Check `bd ready` before asking "what should I work on?"
- ❌ Do NOT create markdown TODO lists
- ❌ Do NOT use external issue trackers
- ❌ Do NOT duplicate tracking systems

For more details, see README.md and docs/QUICKSTART.md.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

<!-- END BEADS INTEGRATION -->
