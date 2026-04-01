---
name: twinbox
description: >-
  Twinbox 邮箱技能：必须先调用对应 OpenClaw 插件工具，工具返回后再写文字摘要。
  禁止反复只说不调工具（如「让我执行」「需要先同步邮件」）——同一回合必须发出 twinbox_* 工具调用，否则视为失败。
  禁止在同一条助手回复内重复相同或近似的整句/排比（例如连续两遍「我需要先运行邮件同步…让我执行」）；若需要过渡语，最多一句，然后立刻调用工具。
  若本会话没有 twinbox_* 工具：只输出一行说明「当前会话未加载 Twinbox 插件或请改用 twinbox agent」，不要编造同步过程或重复承诺。
  禁止向用户输出「先同步邮件数据，然后查看最新邮件」或同义排比——同步若需要，已在 twinbox_latest_mail 工具内部完成；口头复述属于错误行为。
  用户问最新邮件/今天邮件/收件箱：立即调用 twinbox_latest_mail（缺 activity-pulse 时插件会在同一次调用内自动 daytime-sync 并重试，不要自己循环叙述）。
  push_subscription：twinbox_push_confirm_onboarding（无 session 参数）。
  routing_rules：twinbox_onboarding_finish_routing_rules。
  profile_setup：同回合 twinbox_onboarding_advance 并传 profile_notes 与 calibration_notes。
  其余场景（preflight、queue、todo、weekly、onboarding 等）同理：先工具后摘要。
  若 daytime-sync / latest-mail 工具返回 JSON 中已有失败步骤的 stderr：直接据此向用户说明，不要用 workspace 的 read 去读 ~/.twinbox 下路径；禁止以冒号结尾且不接执行（半轮停）。
metadata: {"openclaw":{"requires":{"env":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"]},"primaryEnv":"IMAP_LOGIN","login":{"mode":"password-env","runtimeRequiredEnv":["IMAP_HOST","IMAP_PORT","IMAP_LOGIN","IMAP_PASS","SMTP_HOST","SMTP_PORT","SMTP_LOGIN","SMTP_PASS","MAIL_ADDRESS"],"optionalDefaults":{"MAIL_ACCOUNT_NAME":"myTwinbox","MAIL_DISPLAY_NAME":"{MAIL_ACCOUNT_NAME}","IMAP_ENCRYPTION":"tls","SMTP_ENCRYPTION":"tls"},"stages":["unconfigured","validated","mailbox-connected"],"preflightCommand":"twinbox mailbox preflight --json"}}}
---

# twinbox

本技能用于 Twinbox 邮箱 onboarding、只读预检、最新邮件摘要、队列管理、线程进展查询、每周简报查看、队列刷新、以及 OpenClaw 托管环境下的部署调试。

## 会话与验证机制

Twinbox 邮件状态由 **OpenClaw 宿主上的 `twinbox` / `twinbox-orchestrate`** 生成，在 **`twinbox` agent 会话**（工具策略 + 会话历史 + Gateway）中消费。空回复、"只读 SKILL"、静默回合等回归问题通过**会话设计与测试流程**（需要时新建会话、bootstrap 回合、长套件拆分、可选 **`plugin-twinbox-task`** 工具）解决，详见 `integrations/openclaw/prompt-test.md` 和 `scripts/run_openclaw_prompt_tests.py`。

已知 OpenClaw 限制（2026-03-27 在部分网关托管模型上确认）：OpenClaw 仅将本技能的 **`description`** 注入系统提示，`~/.openclaw/skills/twinbox/SKILL.md` 其余内容仅在 agent 主动读取文件时可见。在这些环境中，调用工具后可能立即停止并返回 `payloads=[]`、`assistant.content=[]`，或短文本如"让我执行命令："。**插件宿主：**当 `plugin-twinbox-task` 已加载时使用原生 **`twinbox_onboarding_*`** 工具；否则 `twinbox onboarding …` 可能走通用 `exec` 并产生相同空气泡。

**如果 UI 在您回答 `profile_setup` 后无内容显示：** 阶段尚未推进——需要宿主运行 **`twinbox_onboarding_advance`**（插件）或 **`twinbox openclaw onboarding-advance --profile-notes "…" --calibration-notes "…"`**。发一条后续消息要求 agent 用您上一条回复的内容调用 **`twinbox_onboarding_advance`**，然后总结 JSON；或自行在 shell 中运行 CLI 并将 stdout 粘贴到聊天中。

推荐宿主端变通方案：新建一个 **`twinbox` 会话**，先发一条 **bootstrap** 消息让 agent 读取 `~/.openclaw/skills/twinbox/SKILL.md` 并在同一回合运行对应的 `twinbox ... --json` 命令；若会话仍返回空内容，以宿主 shell `twinbox ... --json` 的输出作为机器可读验证的事实来源。优先使用原生插件工具；工具不可用时使用 bootstrap 路径。

## 回合契约

**所有** twinbox 命令执行（邮件、队列、摘要、onboarding、部署、调度、规则等）：先运行对应的 `twinbox` 命令并加 `--json`，然后用文字摘要回复。禁止以纯工具调用结束而无文字回复。`payloads=[]` 或 `assistant.content=[]` 的回合永远是失败。

### 禁止断链（弱工具模型关键）

这类模型经常**在叙述后停下**（"现在导入到 Twinbox：""下一步执行…"）**而不调用**下一个工具——将此视为**硬失败**加以预防。

- **禁止：** 在助手消息中表达要执行 Twinbox 操作的意图，但在**同一助手回合**（或宿主将工具输出与文本分开时的**紧随其后**的助手回合）中未调用对应工具。
- **`exec` / shell 写入文件后**（如 `/tmp/...md`）：**同一回合**必须继续调用 **`twinbox_context_import_material`**（插件）或 **`twinbox context import-material PATH --intent reference|template_hint`** —— 不要在"文件已创建"后停下。
- **import-material 之后**（onboarding 期间）：若材料步骤已完成，**同一回合或下一回合**调用 **`twinbox_onboarding_advance`**（适当时），并在可见文字中总结 **`completed_stage` / `current_stage` / `prompt`**。
- **`routing_rules` 阶段：** 用户描述过滤规则（或说**跳过**）时，**同一回合：** 优先 **`twinbox_onboarding_finish_routing_rules`**（`rule_json` 或 `skip_rules: true`）——一次插件执行完成 add + advance；回退方案为 **`twinbox_rule_add`** 然后 **`twinbox_onboarding_advance`** → **可见摘要**。用户已经回答后不要再停下来问"要不要配规则"。
- **`push_subscription` 阶段：** 用户说**确认**（或同意 daily/weekly）时，**同一回合：** 优先 **`twinbox_push_confirm_onboarding`**（仅 `daily`/`weekly` —— **无 session 参数**，不会在 session_target 上卡住）。备选：**`twinbox_onboarding_confirm_push`** 加可选 `session_target`（默认见插件）。**不要**停下来"查询会话信息"；直接调工具并总结 JSON。
- **标准顺序：** 写入或获取文件路径 → **import-material** → （需要时）**onboarding_advance** → **可见摘要**。跳过中间环节是常见失败模式。

### Onboarding：用户回复后推进（关键）

`profile_setup`、`material_import`、`routing_rules`、`push_subscription` 等阶段是**对话优先**的：在聊天中收集回答，但**不会持久化且阶段不会推进**，直到 Twinbox 宿主运行 **advance** 命令。**OpenClaw 有 `plugin-twinbox-task`：** 优先 **`twinbox_onboarding_advance`**（封装 `twinbox openclaw onboarding-advance`）。**Shell / 无插件：** **`twinbox onboarding next --json`** 带相同可选参数等效。不要告诉用户必须输入命令名 —— **你**必须在他们的回答准备好后调用工具或 CLI。

#### 自动化 profile_setup（agent 规则 —— 优先执行）

当 **`current_stage` 为 `profile_setup`** 且用户消息包含实质性回答（职位、习惯、本周重点、忽略什么、CC 处理等）时：

1. **同一助手回合（优先）：** 调用 **`twinbox_onboarding_advance`** 并传 **`profile_notes`** 和 **`calibration_notes`** —— 简洁总结用户所说内容（不做二次 LLM 改写；你就是总结者）。仅在用户明确说明 CC 与主收件箱偏好时使用 **`cc_downweight`** `on`/`off`。
2. **工具返回后立即在同一回合：** 写**可见**回复，总结 **`completed_stage`**、**`current_stage`** 和下一段 **`prompt`**（引用或转述）。**工具调用后省略可见文字（空气泡）永远是失败。**
3. **如果平台无法在一次回复中附加工具后文字：** 在**紧随其后**的助手消息中调用 **`twinbox_onboarding_advance`**（如尚未完成），然后总结 —— **不要**等用户要求"advance"或"next command"。

#### 自动化 routing_rules（agent 规则）

当 **`current_stage` 为 `routing_rules`** 且用户消息是**具体规则请求**（如自动归档/降权某类邮件）或明确**跳过**时：

1. **优先（更稳定）：** 构建 **`rule_json`**，然后调用 **`twinbox_onboarding_finish_routing_rules`** —— 插件在**一次工具执行**中完成 **`rule add` + `onboarding-advance`**，模型只需做**一次**工具决策（弱宿主在使用两个独立工具时经常丢掉第二个调用）。用户明确跳过（无 `rule_json`）时用 **`skip_rules: true`**。
2. **回退：** **`twinbox_rule_add`** 然后 **`twinbox_onboarding_advance`**，同一助手回合。
3. **紧随其后：** 可见文字包含 **`completed_stage`**、**`current_stage`**、下一段 **`prompt`**。**禁止**以纯工具调用或"下一步"叙述（无工具）结束。

**为什么有时"成功"有时"失败"：** 工具调用在每个回合中是**概率性**的；两个链式工具使失败率翻倍。上述原子工具将其减少到**一次**调用。

**UI 空白恢复**（用户发了规则但无回复后）：用用户消息中的 **`rule_json`** 调用 **`twinbox_onboarding_finish_routing_rules`**，或 shell 执行 **`twinbox rule add …`** 然后 **`twinbox openclaw onboarding-advance --json`**。

#### 自动化 push_subscription

当 **`current_stage` 为 `push_subscription`** 且用户确认（如**确认**）时：

1. **优先：** **`twinbox_push_confirm_onboarding`** 仅带可选 **`daily` / `weekly`** —— schema **无 `session_target`**，模型不会卡在"查找会话"上。
2. **备选：** **`twinbox_onboarding_confirm_push`** 加可选 **`session_target`**（默认：env，否则 **`agent:twinbox:main`**）。
3. **工具返回后：** 可见摘要包含订阅信息 + **`completed_stage`** / **`current_stage`**。

**Shell（无插件）：** `twinbox openclaw onboarding-confirm-push agent:twinbox:main --daily on --weekly on --json`（若使用非 main 目标请调整 session）。

**profile_setup 持久化细节：** CLI 参数 **`--profile-notes`** / **`--calibration-notes`** / **`--cc-downweight`** 映射到 `runtime/context/human-context.yaml`（`profile_notes` / `calibration`）加 `twinbox.json.preferences.cc_downweight.enabled`。Phase 2/3 **和 Phase 4** 的 **`context-pack.json`** 将这些暴露为 `human_context.onboarding_profile_notes` / `human_context.calibration_notes`。旧版 `manual-facts.yaml` / `manual-habits.yaml` / `instance-calibration-notes.md` / onboarding `profile_data.*` 在首次读取时迁移；之后统一文件为权威来源。无这些参数的阶段使用 `twinbox context upsert-fact` / `profile-set` 持久化文本。**`twinbox onboard openclaw`** 在 LLM 校验通过后可在 TTY 内多行粘贴画像/校准/参考文（单独一行 `.` 结束；不回显正文），可选 LLM 润色；跳过：`--skip-tty-context-bundle`。部署成功后默认继续在 TTY 完成 **routing_rules** 与 **push_subscription**（需 bridge timer）；仅对话完成：`--skip-tty-routing-push`。**material_import** 阶段先展示 `config/weekly-template.md`；用户要调整章节时转为 Markdown 并用 **`twinbox_context_import_material`**（插件）或 `twinbox context import-material FILE --intent template_hint`（或宿主上 **`twinbox context import-material --stdin --label STEM --intent …`**）导入，使后续 weekly digest 自动跟随 —— **文件存在的同一回合**完成，不要说"下一步再导入"。

**UI 空闲恢复**（用户发了画像但无助手文字/空气泡后）：(1) 用用户**上一条**消息的 `profile_notes` / `calibration_notes` 调用 **`twinbox_onboarding_advance`**；(2) **`twinbox_onboarding_status`** 然后 **`twinbox_onboarding_advance`**（或 `twinbox onboarding status --json` 然后 `twinbox onboarding next --json` 带相同画像参数）。若 Gateway 仍丢内容，在**宿主 shell** 运行 **`twinbox openclaw onboarding-advance --profile-notes '…' --calibration-notes '…' --json`** 并将 stdout 粘贴到聊天。

**会话：** onboarding 交接优先使用**专用 `twinbox` agent** —— 非 `main` —— 以确保技能注入、工具和 `integrations/openclaw/DEPLOY.md` 匹配。

## 适用场景

- 邮箱环境收集与登录预检：`twinbox mailbox preflight --json`
- 总结"最新邮件情况"、"今天更新"、"今天发生了什么"
- 列出紧急事项、待回复、SLA 风险
- 通过 `twinbox queue ...` 忽略/完成/恢复队列可见线程
- 通过 `twinbox schedule ...` 列出/覆盖/重置运行时调度配置
- 查询某个线程/主题/项目/关键词的最新进展
- 查看 daily / pulse / weekly 摘要
- 从当前队列状态建议操作或审核项
- 检查 Twinbox 运行时是否已挂载且可在当前 OpenClaw 宿主上运行
- 通过 `twinbox-orchestrate schedule --job ...` 或 `run --phase <n>` 刷新流水线产物
- 解释 `runtime/validation/phase-4/` 下的 urgent / pending / SLA / weekly 输出
- 诊断已部署的 Twinbox/OpenClaw 技能为何缺失、受阻、过期或不刷新
- 一键 **OpenClaw 宿主接线**：roots 初始化、`openclaw.json` 合并、`SKILL.md` 同步、gateway 重启（`twinbox deploy openclaw`）；窄范围回退：`twinbox deploy openclaw --rollback`（不删除 `~/.twinbox`）
- **完全卸载** Twinbox：停止 daemon / OpenClaw bridge、删除 CLI 二进制、删除状态和配置指针、清理 shell 和 OpenClaw 环境（见下文 **完全卸载** 段落）

## 完全卸载（CLI、状态、环境）

**不等同于** `deploy openclaw --rollback`（后者保留 `~/.twinbox` 和 PATH 上的 `twinbox`）。在 `twinbox` **仍可运行时**执行：`daemon stop` → `deploy openclaw --rollback [--remove-config]` → `host bridge remove` / `schedule disable JOB`（如需）。

**二进制：** `pip uninstall -y twinbox-core`（删除 `twinbox`、`twinbox-orchestrate`、`twinbox-eval-phase4`）；删除 PATH 上其他 `twinbox`（如 `~/.local/bin`、`/usr/local/bin`）；可选仓库产物：`dist/twinbox*`、`cmd/twinbox-go/twinbox`。

**数据、OpenClaw、环境：** `rm -rf ~/.twinbox`（破坏性——先备份）；删除 `~/.config/twinbox/*`（如存在）；删除 `~/.openclaw/skills/twinbox`，按 `integrations/openclaw/DEPLOY.md` 卸载 `plugin-twinbox-task`，然后 `openclaw gateway restart`。从所有设置处（shell、systemd、OpenClaw 技能 env、CI）清除 **`TWINBOX_*`**、**`TWINBOX_SETUP_*`** 和本技能 `metadata.openclaw.requires.env` 中的邮箱变量。新 shell：`command -v twinbox` 应为空。

## 任务入口

**任务请求的必需步骤：**

1. 将用户请求匹配到下方列表中的命令。
2. 立即执行该命令。
3. 写一段文字回答总结真实输出。

读取本文件仅是第 0 步。回合**未完成**直到执行了命令（第 2 步）并写了文字回答（第 3 步）。若目前只读了文件或记忆，立即进入第 2 步——不要结束回合。

| 用户意图 | 命令 |
|----------|------|
| 最新邮件 / 今日摘要 / "最新邮件情况" / "帮我查看下最新的邮件情况" | `twinbox task latest-mail --json`（用户要求未读时加 `--unread-only`） |
| "我有哪些待办 / 待回复 / 最值得关注的线程" | `twinbox task todo --json` |
| 暂时忽略某个线程 / 标记已处理但先别再提醒 | `twinbox queue dismiss THREAD_ID --reason "..." --json`；OpenClaw 插件：`twinbox_queue_dismiss`（`thread_id`，可选 `reason`） |
| 标记某个线程已完成（须落库，聊天里打 ✅ 不算） | `twinbox queue complete THREAD_ID --action-taken "..." --json`；OpenClaw 插件：`twinbox_queue_complete`（`thread_id`，可选 `action_taken`） |
| 恢复一个 dismissed/completed 线程 | `twinbox queue restore THREAD_ID --json` |
| 查看当前调度配置 | `twinbox schedule list --json` 或 OpenClaw 工具 `twinbox_schedule_list` |
| 修改 daily/weekly/nightly 调度时间 | `twinbox schedule update JOB_NAME --cron "30 9 * * *" --json` 或 OpenClaw 工具 `twinbox_schedule_update` |
| 恢复某个调度到默认时间 | `twinbox schedule reset JOB_NAME --json` 或 OpenClaw 工具 `twinbox_schedule_reset` |
| 启用某个后台调度（创建 OpenClaw cron job） | `twinbox schedule enable JOB_NAME --json` 或 OpenClaw 工具 `twinbox_schedule_enable` |
| 禁用某个后台调度（删除 OpenClaw cron job） | `twinbox schedule disable JOB_NAME --json` 或 OpenClaw 工具 `twinbox_schedule_disable` |
| "某个事情进展如何" / 查询进展 | `twinbox task progress QUERY --json` |
| 邮箱状态 / 环境诊断 | `twinbox task mailbox-status --json` |
| 自动探测邮件服务器配置 | `twinbox mailbox detect EMAIL --json` |
| 查看当前配置文件 | `twinbox config show --json` |
| 配置邮箱凭据（自动探测或显式主机参数，写入 `twinbox.json`） | `twinbox mailbox setup --email EMAIL --json` 或 `twinbox config mailbox-set --email EMAIL --json`（密码从 `TWINBOX_SETUP_IMAP_PASS` 注入）或 OpenClaw 工具 `twinbox_mailbox_setup` |
| 配置 LLM API（写入 `twinbox.json`） | `twinbox config set-llm --provider openai\|anthropic --model MODEL --api-url URL --json`（key 从 `TWINBOX_SETUP_API_KEY` 注入；须显式传 model 和 api-url）或 OpenClaw 工具 `twinbox_config_set_llm`；与 OpenClaw 默认模型一致时可 `twinbox config import-llm-from-openclaw --json`（需 `openclaw.json` 内联 `apiKey`）或插件 `twinbox_config_import_llm_from_openclaw` |
| 配置 Twinbox 偏好（含 CC 降权） | `twinbox config set-preferences --cc-downweight on\|off --json` |
| 导入会议纪要/项目台账等外部材料进入周报 | OpenClaw 有插件时优先 **`twinbox_context_import_material`**（`source_path` + `intent`）；否则 `twinbox context import-material FILE --intent reference`（随后跑 `twinbox-orchestrate run --phase 4` 或等常规调度） |
| 自定义周报模板（标题/章节顺序/措辞） | 先展示 `config/weekly-template.md`，再把用户确认的新模板用 **`twinbox_context_import_material`**（`intent=template_hint`）或 `twinbox context import-material FILE --intent template_hint` 导入 |
| 配置 Twinbox integration 默认值 | `twinbox config integration-set --use-fragment yes\|no [--fragment-path PATH] --json` |
| 配置 OpenClaw 默认值 | `twinbox config openclaw-set [--home PATH] [--bin NAME] [--strict\|--no-strict] [--sync-env\|--no-sync-env] [--restart-gateway\|--no-restart-gateway] --json` |
| OpenClaw 安装总向导（唯一公开向导入口；**Apply setup 后默认完成**：OpenClaw 合并 + plugin/tools 可观测性 + **vendor-safe bridge user timer 安装 + health dry-run**；`phase2_ready=true` 才 handoff Phase 2；逃生口 `--skip-bridge`；部署成功后默认尝试 **daemon start**，`--no-start-daemon` 跳过） | `twinbox onboard openclaw [--skip-bridge] [--no-start-daemon] --json` |
| OpenClaw 宿主接线高级入口（与 onboard 共享同一套 prerequisite bundle；默认安装 bridge；成功后默认 **daemon start**，`--no-start-daemon` 跳过） | `twinbox deploy openclaw --json`（`--dry-run`；`--no-restart`；`--no-env-sync`；`--strict`；`--skip-bridge`；`--twinbox-bin`；`--no-start-daemon`；可选 `--fragment` / `--no-fragment`） |
| 撤销上述宿主接线（不删 `~/.twinbox`；**同时移除 bridge user units**） | `twinbox deploy openclaw --rollback --json`（可选 `--remove-config`） |
| Vendor-safe OpenClaw bridge（systemd user 单元只调用已安装 `twinbox`，不依赖 repo `scripts/`） | `twinbox host bridge install\|remove\|status\|poll [--dry-run] [--openclaw-bin …]` |
| OpenClaw 内 Phase 2 onboarding 与上下文材料（对应 CLI：`twinbox openclaw …` / `twinbox context …`） | 插件：`twinbox_context_import_material` / `twinbox_onboarding_start` / `twinbox_onboarding_status` / `twinbox_onboarding_advance` / **`twinbox_onboarding_finish_routing_rules`**（routing_rules 阶段优先） / **`twinbox_push_confirm_onboarding`**（push_subscription 用户确认时优先，仅 daily/weekly） / `twinbox_onboarding_confirm_push` |
| 每周简报查询 | `twinbox task weekly --json` |
| 管理语义路由规则 / "以后别把这类邮件派给我" | `twinbox rule list --json` / `twinbox rule add --rule-json ...` |
| 测试路由规则对近期线程的效果 | `twinbox rule test --rule-id RULE_ID --json` |
| 启动 onboarding 流程 | `twinbox onboarding start --json`（人类可读输出会以 "Phase 2 of 2" 继续旅程） |
| 查看 onboarding 进度 | `twinbox onboarding status --json`（人类可读输出会以 "Phase 2 of 2" 继续旅程） |
| 推进 onboarding 到下一阶段 | `twinbox onboarding next --json`（人类可读输出会以 "Phase 2 of 2" 继续旅程） |
| 用户已用自然语言答完当前阶段（画像/材料/规则/推送等） | OpenClaw 有插件时：**同轮**先 **`twinbox_onboarding_advance`**（画像阶段必带 `profile_notes` / `calibration_notes` 要点）；否则 **`twinbox onboarding next --json`**（画像同上，可加 `--cc-downweight off` 若用户明确 CC 为主要工作）。然后**必须**根据返回 JSON 总结 `completed_stage`、`current_stage`、下一段 `prompt`（不可只调工具无正文） |
| 后台 JSON-RPC daemon（省 Python 冷启动；可选） | `daemon start` / `onboard`·`deploy` 触发的拉起。`twinbox daemon status --json`（含 `cache_stats` 等）。Socket：`$TWINBOX_STATE_ROOT/run/daemon.sock`。Go 交付默认可为 `twinbox`（**dial 失败**时静默跑一次 `daemon start` 再重试 RPC；`TWINBOX_NO_LAZY_DAEMON=1` 关闭）；仍失败则 `exec` Python；vendor 会校验 `MANIFEST.json`。`twinbox install --archive …` 解压到 `vendor/` 并写 `code-root`（开发可用 `TWINBOX_CODE_ROOT` 覆盖） |
| 多邮箱 profile（共享 vendor、独立 state） | `twinbox --profile NAME …`（`TWINBOX_STATE_ROOT=~/.twinbox/profiles/NAME/state`，`TWINBOX_HOME=~/.twinbox`） |
| Phase loading（Python 入口） | `twinbox loading phase1` … `phase4`（编排层为 `python -m twinbox_core.*`，无 `scripts/phase*.sh` 依赖；phase1/4 仍使用 himalaya CLI 传输） |
| 将 `twinbox_core` 同步到 vendor（宿主 PYTHONPATH） | `twinbox vendor install`；`twinbox vendor status --json`（`integrity_ok` / `file_count`）。装好后：`PYTHONPATH="$TWINBOX_HOME/vendor"` 或 `…/state/vendor`（无 profile 时二者常相同）+ `python3 -m twinbox_core.task_cli …` |
| 订阅推送（**daily / weekly 可分别开关**；首次开 daily 会尝试把 `daily-refresh` 默认改为 hourly 且无既有 override 时） | `twinbox push subscribe SESSION_ID [--daily on\|off] [--weekly on\|off] --json` |
| 调整已有订阅的 cadence | `twinbox push configure SESSION_TARGET --daily on\|off --weekly on\|off --json` |
| 列出推送订阅 | `twinbox push list --json` |
| 查看某个线程的完整内容 / "把这个线程内容返回给我看看" / "先读这个线程" | `twinbox thread inspect THREAD_ID --json` 或 OpenClaw 工具 `twinbox_thread_inspect` 且传 `thread_id` |
| 解释为什么某个线程是紧急/待处理 | `twinbox thread explain THREAD_ID --json` |
| 每日摘要 | `twinbox digest daily --json`（人类可读模式为 Markdown；稳定消费优先 `--json`） |
| 每周简报 | `twinbox digest weekly --json`（人类可读模式为 Markdown，按默认 `config/weekly-template.md` 或最新 `template_hint` 的标题/章节顺序渲染；若已有 `runtime/validation/phase-4/daily-ledger/` snapshots，会把本周早些时候已退出 action surface 的线程轨迹补回 `important_changes`；仍不是 daily 自动累计；稳定消费优先 `--json`） |
| 建议下一步操作 | `twinbox action suggest --json` |
| 执行一个建议操作 | `twinbox action materialize ACTION_ID --json` |
| 审核项 | `twinbox review list --json` / `twinbox review show REVIEW_ID --json` |
| 刷新日间/小时级预测（邮件数据同步） | OpenClaw 插件：**`twinbox_daytime_sync`**（默认 `daytime-sync`）；CLI：`twinbox-orchestrate schedule --job daytime-sync --format json` |
| 刷新完整的夜间/每周流水线 | OpenClaw 插件：**`twinbox_daytime_sync`**（`job='nightly-full'`）；CLI：`twinbox-orchestrate schedule --job nightly-full --format json` |
| **完全卸载** | 见上节 **完全卸载**（rollback → 删 pip/二进制 → 删 `~/.twinbox` → skill/plugin → 清 env） |

## 任务路由规则

- 用户确认线程**已完成**或**忽略**时，必须持久化队列状态：运行 `twinbox queue complete` / `queue dismiss` 加 `--json`，或调用 OpenClaw 工具 `twinbox_queue_complete` / `twinbox_queue_dismiss`。从 `task todo`、`task latest-mail` 或 `thread inspect` 解析 `thread_id` —— 每周简报的文字行不是线程 key。
- `runtime/context/user-queue-state.yaml` 在首次成功 `queue complete` 或 `queue dismiss` 时**创建**；之前不存在是正常的。
- 先运行命令（`--json`），然后用纯文字为用户总结 stdout；**缺失邮件工件**（如 `activity-pulse.json` / `weekly-brief-raw.json`）或**队列中找不到 thread_id** 时，`--json` 仍 **exit 0**，stdout 为单帧 JSON（含 `ok: false`、`recovery_tool` / `recovery_hint`），与 `task latest-mail` 一致——勿仅依赖非零退出码判断失败。
- 常见用户提问优先用 `twinbox task ...`；这些是薄封装，不是第二条流水线
- 查询最新邮件情况（含中文各种变体）时，先用 `twinbox task latest-mail --json`；除非连接性是明确问题，否则不要从 `preflight` 开始。用户明确要求"未读"时传 `--unread-only` 或工具参数 `unread_only: true`。**OpenClaw 插件 `twinbox_latest_mail`：** 若 `activity-pulse.json` 缺失，插件会在同一次工具调用内自动运行 `daytime-sync` 并重试——不要反复叙述「让我执行」；等工具输出即可。
- 查看某个线程的完整内容/详情/状态时，优先 `twinbox thread inspect THREAD_ID --json` 或 `twinbox_thread_inspect`；非精确查找时才用 `task progress`。
- 若 `activity-pulse.json` 缺失或过期（工具输出会包含 `recovery_tool: "twinbox_daytime_sync"`），**立即调用 `twinbox_daytime_sync`**（插件）或 `twinbox-orchestrate schedule --job daytime-sync`（CLI），然后重新调用原始任务工具并总结
- `daytime-sync` 现通过增量 Phase 1 入口（`python -m twinbox_core.incremental_sync`）进入，然后执行 Phase 3/4 日间预测
- 增量 Phase 1 路径使用 UID 水印，UIDVALIDITY 变化时自动回退到现有全量加载器
- 默认调度定义位于 `config/schedules.yaml`；`twinbox schedule update/reset` 写入 `runtime/context/schedule-overrides.yaml` 并尝试同步对应的 Twinbox OpenClaw cron job（通过 `openclaw cron list/edit/add`）
- Gateway 访问失败时，命令仍保留运行时 override 并在 JSON 输出中暴露 `platform_sync.status=error`
- 调度提示优先使用原生 OpenClaw 工具 `twinbox_schedule_list` / `twinbox_schedule_update` / `twinbox_schedule_reset` / `twinbox_schedule_enable` / `twinbox_schedule_disable`，不用通用 `cron` 或 workspace 搜索
- onboarding 邮箱配置优先使用原生 OpenClaw 工具 `twinbox_mailbox_setup`（通过 env 传递密码，不通过 CLI 参数）
- onboarding LLM API 配置优先使用原生 OpenClaw 工具 `twinbox_config_set_llm`（通过 env 传递 api_key）
- onboarding 邮箱/LLM 后优先 `twinbox_onboarding_start` / `twinbox_onboarding_status` / `twinbox_onboarding_advance`；**push_subscription** 优先 **`twinbox_push_confirm_onboarding`**（无 session 字段）；否则 `twinbox_onboarding_confirm_push`，避免仅依赖 `onboarding next` 的占位文案
- 用户用自然语言回答 **profile_setup** 后，**不要**在未调用 **`twinbox_onboarding_advance`**（或等效 `onboarding next` / `openclaw onboarding-advance`）**和**可见摘要前结束回合——用户不应该需要自己输入命令名
- **写入或暂存文件**给 Twinbox 后（如 `exec` 到 `/tmp/...`），**不要**在未调用 **`twinbox_context_import_material`**（或 `twinbox context import-material …`）**和**可见摘要前结束回合——不要停在"现在导入…"
- 优先使用 **`twinbox_context_import_material`** 而非通用 shell 处理相同路径，使模型看到**命名工具**而不易断链
- 默认保持只读，除非用户明确要求生成草稿/操作
- **禁止以纯文件读取和无文字回答结束任务回合。** `assistant.content=[]` 或无文字的回合永远是失败——必须先有真实命令输出，再加摘要

## 托管默认值

- Twinbox 工作优先使用专用 `twinbox` agent/会话；保持 `main` 用于通用聊天
- 技能或环境变量变更后，使用新 Twinbox 会话；`skillsSnapshot` 可能冻结旧注入结果
- 托管环境变量应来自 `skills.entries.twinbox.env`；`state root/twinbox.json` 是 Twinbox 配置来源（编排与 Phase LLM 的 `--env-file` 即此路径）。同目录仅有旧版 `.env` 时仍会回退读取；通过 CLI 写入时会合并进 JSON 并移除 `.env`
- 若启用 `plugin-twinbox-task`，优先将 `twinboxBin` 设为 `scripts/twinbox` 的绝对路径；若未设置，保持 `cwd` 准确以便插件自动探测 `<cwd>/scripts/twinbox`，不依赖 Gateway PATH
- 将 OpenClaw 调度执行视为 Twinbox 管理的 bridge cron 事务；当前默认定义来自 `config/schedules.yaml`，非技能 metadata
- Bridge poller 默认路径：`systemd user timer` → `twinbox host bridge poll` → `openclaw gateway call cron.*` → `twinbox-orchestrate schedule --job …`（vendor 安装不依赖 `scripts/twinbox_openclaw_bridge_poll.sh`）

## 安全护栏

- 默认保持只读（Phase 1–4 邮箱 IMAP 仍为只读）
- `queue complete` / `queue dismiss` 仅更新**本地** Twinbox 队列可见性（`user-queue-state.yaml`）；用户要求停止提醒某个**已命名或已确认的特定线程**时使用
- 除非用户明确要求且运行时支持，不要发送、删除、归档或变更邮箱状态
- 不要声称 OpenClaw 自动导入调度 metadata；当前已验证的调度配置来自 `twinbox schedule update/reset` 同步 bridge cron jobs
- 不要将 `openclaw skills info twinbox = Ready` 视为当前会话提示已包含 `twinbox` 的证明
- 不要声称平台已自动运行 `preflightCommand`，除非你有真实执行路径的证据

## 快速检查

- `twinbox task mailbox-status --json`
- `twinbox task latest-mail --json`
- `twinbox task todo --json`
- `twinbox queue dismiss THREAD_ID --reason "已处理" --json`
- `twinbox queue complete THREAD_ID --action-taken "已归档" --json`
- `twinbox queue restore THREAD_ID --json`
- `twinbox schedule list --json`
- `twinbox schedule update daily-refresh --cron "30 9 * * *" --json`
- `twinbox schedule reset daily-refresh --json`
- `twinbox task progress QUERY --json`
- `twinbox digest pulse --json`（人类可读模式为 Markdown；稳定消费优先 `--json`）
- `twinbox-orchestrate roots`
- `twinbox daemon status --json`（daemon 未启用时 `status=stopped` 属正常）
- `twinbox-orchestrate contract --phase 4`
- `twinbox-orchestrate schedule --job daytime-sync --format json`
- `twinbox-orchestrate run --phase 1`
- `twinbox-orchestrate run --phase 4`

## 运行时说明

- `mailbox-connected` 表示只读 IMAP 预检成功
- `status=warn` 带 `smtp_skipped_read_only` 对预检来说是可接受的
- OpenClaw 原生部署应通过 `skills.entries.twinbox.env` 注入邮箱环境变量；`state root/twinbox.json` 是 Twinbox 配置来源（与上条一致：`--env-file` 指向 JSON，无 JSON 时回退 `.env`）
- 如果 Twinbox 部署后不再出现在回答中，先检查环境变量网关，再检查会话级 `skillsSnapshot`
- 如果 Twinbox 命令失败，先验证环境变量、挂载的仓库根目录、`runtime/bin/himalaya`（Linux x86_64/aarch64 上 twinbox 可在首次预检时提取内置 `himalaya`）、以及 OpenClaw 宿主上的 Python 依赖

**Claude Code 技能（更深度的仓库工作流）：** [`.claude/skills/twinbox/SKILL.md`](.claude/skills/twinbox/SKILL.md)
