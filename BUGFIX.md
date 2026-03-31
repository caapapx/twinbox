# BUGFIX — 缺陷与问题解决记录

仓库内**可复用的 bug 根因、缓解措施与相关提交**集中在此；避免散落在 `issue.md`、多份 troubleshooting 或与操作手册混写。

## 与排障文档的分工

| 文档 | 用途 |
|------|------|
| **[BUGFIX.md](./BUGFIX.md)**（本文） | 问题表现、根因分析、修复思路、**相关提交**、验证要点；可按时间追加小节。 |
| [integrations/openclaw/TROUBLESHOOT.md](./integrations/openclaw/TROUBLESHOOT.md) | OpenClaw 宿主侧**操作步骤**、探针命令、回滚与配置核对（runbook）。 |
| [docs/ref/cli.md](./docs/ref/cli.md) 等 ref | 行为契约与命令参考，非个案记录。 |

## 如何追加一条记录

1. 在下方「已归档」增加 `## <短标题>（YYYY-MM-DD）`。
2. 建议包含：**问题表现** → **根因** → **修复或缓解** → **相关提交**（`hash` + 一行说明）→ **验证**。
3. 若仅为部署误配，优先补 **TROUBLESHOOT.md**；若涉及代码/契约变更，在本文记一笔并链到 TROUBLESHOOT 对应节。

---

## 已归档

### OpenClaw `twinbox` agent 会话污染与工具断链

#### 问题表现

在 OpenClaw `twinbox` agent 会话中：

- 第一个问题（如「帮我看下最新的邮件」）正常返回结果。
- 第二个、第三个问题失败；新开会话后第一个问题又正常。

**失败模式：**

- Agent 回复「让我执行命令：」但不调用工具。
- 返回空内容（`payloads=[]` 或 `assistant.content=[]`）。
- 工具调用后立即停止，无文字摘要。

#### 根本原因

**OpenClaw 系统提示限制：** 仅将 SKILL.md 的 **`description` 字段**注入系统提示，文件其余内容需 agent **主动读取**才可见。

**会话污染链：**

1. 第一轮：agent 可能读取完整 SKILL.md，遵守工具调用约束。
2. 第二轮：依赖会话历史，核心约束不在系统提示中。
3. 第三轮：退化为「承诺执行但不调用」。
4. 新会话：重新读取 SKILL.md，恢复。

**弱工具模型：** 部分托管模型在工具调用后易「断链」（只说到执行、或工具后空回复）。

#### 解决方案（缓解）

1. **强化 `description`（已实施）** — 将「先工具后摘要、禁止只说不调」等写入 `SKILL.md` 的 `description`。
2. **Bootstrap 消息（推荐）** — 新会话首条要求读取 `SKILL.md` 并同轮执行 `twinbox task latest-mail --json`（或插件等价工具），避免半轮停。
3. **原生插件工具** — 使用 `twinbox_latest_mail` 等，而非仅靠泛化 `exec`；改后 `openclaw gateway restart`。
4. **会话卫生** — 连续两次失败或空回复时新开会话，勿在同一污染会话内硬磨。

#### 验证步骤（摘要）

- 有 / 无 bootstrap 下连续多轮提问对比；见下文监控与 [integrations/openclaw/prompt-test.md](./integrations/openclaw/prompt-test.md)。

#### 相关提交（示例）

| Hash | 说明 |
|------|------|
| `25a7891` | `fix(skill)`：Turn contract 嵌入 frontmatter `description`，改善 prompt 测试与系统提示可见性。 |
| `71f88c4` | `fix(skill)`：Turn contract 覆盖范围扩展到全部 twinbox 命令。 |
| `0fa7196` | `feat`：反断链 SKILL 规则等（会话行为相关）。 |
| `b1de21c` | `feat`：`twinbox_push_confirm_onboarding` 去掉易引发卡住的 session 字段。 |

#### 参考

- [scripts/run_openclaw_prompt_tests.py](./scripts/run_openclaw_prompt_tests.py)
- [.agents/skills/twinbox/SKILL.md](./.agents/skills/twinbox/SKILL.md) / 仓库根 [SKILL.md](./SKILL.md)

#### 监控

在 `~/.openclaw/logs/` 关注工具成功率、空响应率、会话长度与失败率。

---

## 附录 A：`master` 上提交主题时间线（含 `fix:` / `fix(` / `hotfix`）

下列由下面命令生成，**仅反映提交摘要行**，截至文档编写时的快照；后续以 `git log` 为准。

```bash
git log --format='%h %ad %s' --date=short master \
  | grep -iE ' (fix|hotfix|repair)(\(|:)'
```

| 日期 | Hash | 摘要 |
|------|------|------|
| 2026-03-31 | 9dd587e | fix: surface onboard errors when OpenClaw CLI missing (master-en) |
| 2026-03-30 | 54149b1 | fix: parse vendor tarball version without tomllib (Python <3.11) |
| 2026-03-30 | d408016 | fix: return structured json recovery on missing pulse/thread |
| 2026-03-30 | c26b427 | fix: optional session_target for onboarding_confirm_push with safe defaults |
| 2026-03-30 | dc3f38d | fix: add start_daemon to run_openclaw_deploy (match onboard/task_cli) |
| 2026-03-30 | d1daa44 | fix: ignore stale fragment_path in twinbox.json; require explicit tools integration choice |
| 2026-03-30 | a7e8a10 | fix: resolve code root to repo root when cwd is under cmd/twinbox-go |
| 2026-03-30 | eb12b7a | fix: explain skipped tools-fragment prompt when file missing |
| 2026-03-30 | 0b5e6f8 | fix: reset auto mailbox login on email change |
| 2026-03-30 | b74383f | fix: use merged mailbox env for immediate validation |
| 2026-03-29 | 024ea99 | fix(phase4): loading, calibration, recipient_role, dry-run; refactor(prompt): fragments and system/user split |
| 2026-03-28 | 83baa84 | fix(context): feed onboarding profile notes into Phase 2/3 context packs |
| 2026-03-28 | 7346380 | fix(onboard): strip TTY inline secrets and polish OpenClaw handoff |
| 2026-03-28 | 0ae7fcc | fix: always shorten onboard secret keep prompt |
| 2026-03-28 | bd3e820 | fix: shorten onboard secret prompt on narrow tty |
| 2026-03-28 | dfc47f9 | fix: cap onboard secret mask width |
| 2026-03-28 | 19f5722 | fix: validate existing llm on openclaw onboard |
| 2026-03-28 | 6f4c797 | fix: include HTTP error body in llm validation |
| 2026-03-28 | e94856f | fix: map vendor LLM JSON keys (APIKey, modelId, openai_url) in twinbox.json |
| 2026-03-28 | a71b8dd | fix: OpenAI base URL + /chat/completions; LLM validate fail returns to setup menu |
| 2026-03-28 | 0ca63f7 | fix: append /chat/completions for OpenAI-style LLM_API_URL base roots |
| 2026-03-28 | b9525b5 | fix: stop onboard wizard when LLM validation fails (no silent continue) |
| 2026-03-28 | c6b832e | fix: security prompt defaults to No; explicit Yes required to continue |
| 2026-03-28 | acec491 | fix: uniform journey spine gap (one blank) between rail and each tee |
| 2026-03-28 | 724e147 | fix: journey rail continuous spine; tee row ◇  title  ──┐; wider inner padding |
| 2026-03-28 | 986d667 | fix: emit journey completion notes so rail nodes update after each step |
| 2026-03-28 | 35c75ab | fix: journey node on spine tee line (◇──┐), not inside card body |
| 2026-03-28 | fee9d4c | fix: journey T-rail connects cards; note glyphs ◆ configured ◇ pending |
| 2026-03-28 | 66245c7 | fix: improve onboarding and config terminal feedback |
| 2026-03-28 | d620c05 | fix(onboard): align wordmark row width, TWINBOX uppercase block |
| 2026-03-28 | 7df1c29 | fix(onboard): README wordmark + framed header, drop TWINBOX banner |
| 2026-03-28 | 6a5a336 | fix: vertical select redraw clears previous frame height |
| 2026-03-28 | 808867a | fix: align mailbox validation flow with llm |
| 2026-03-28 | 3ebf854 | fix: remove implicit llm defaults |
| 2026-03-28 | ecde8e3 | fix: defer llm validation until after prompts |
| 2026-03-28 | c7480d0 | fix: stabilize onboarding tty rendering |
| 2026-03-27 | 25a7891 | fix(skill): 将 Turn contract 嵌入 frontmatter description，修复 prompt 测试脚本 |
| 2026-03-27 | 71f88c4 | fix(skill): Turn contract 范围扩展到全部 twinbox 命令 |
| 2026-03-27 | 00bcd2a | fix: 修复 uninstall 退出码、PyYAML 依赖、os import 及 fragment example schema |
| 2026-03-27 | d12cde7 | fix: auto-detect twinbox plugin wrapper |
| 2026-03-27 | cb9630b | fix: add missing has_calibration key to _build_human_context |
| 2026-03-27 | 6a952bc | fix: drop code-root fallback for state root; default to ~/.twinbox everywhere |
| 2026-03-27 | b659003 | fix: separate state root to ~/.twinbox and rewrite DEPLOY §3.3-3.4 |
| 2026-03-26 | 9883c44 | fix: material preview reads Phase 4 context-pack for lifecycle_flow stats |
| 2026-03-26 | 5aa6afd | fix: align phase4 normThread with phase3 strip_date_suffix and (count) suffix |
| 2026-03-26 | 0b534de | fix: inspect exact thread content in openclaw |
| 2026-03-26 | 2d90566 | fix(openclaw): handle tool arguments robustly for rule commands |
| 2026-03-26 | 28b78ab | fix: resolve recipient_role unknown by falling back to envelope To field and fix phase4 race condition |
| 2026-03-26 | 99e1d39 | fix: pass recipient_role to phase 4 context and fix json parsing in semantic intent |
| 2026-03-25 | 53c38a4 | fix: restore group routing in refresh and progress |
| 2026-03-25 | 1be8538 | fix: distinguish group-routed mail from cc-only |
| 2026-03-19 | e9db358 | fix: resolve .gitignore merge conflict from stash pop |
| 2026-03-19 | 321d3f7 | fix: harden llm json cleanup |
| 2026-03-19 | 5f80c73 | fix: reduce polecat exploration in formulas |
| 2026-03-19 | 83b02cd | fix: sync polecat worktrees before sling |
| 2026-03-19 | 84c5777 | fix: split phase4_merge.sh from parallel script to avoid duplicate LLM calls |
| 2026-03-19 | d8cff41 | fix: gitignore .beads/, .claude/, .runtime/ (local agent dirs) |
| 2026-03-19 | 42887f1 | fix: gitignore .beads/, .claude/, .runtime/ local dirs |

（共 58 条；合并提交、`feat`/`docs` 等不含上述模式的修复请用 `git log --grep` 另行检索。）
