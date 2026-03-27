# OpenClaw Prompt Test

用于手工验证当前 OpenClaw + Twinbox 集成面的 prompt 集。

**会话与测试口径**：探针与话术验收应在 **OpenClaw Gateway + `twinbox` agent** 下进行；长套题用 **分段 session + bootstrap**（见下文「自动化」与 `scripts/run_openclaw_prompt_tests.py`）。空白气泡、半轮停、后半段全空优先按 **会话长度 / Gateway 与 Web 控制面链路** 排查（见「Control UI 完全空白」），与具体用哪种编辑器无关。

目标：

- 先验证真实用户话术是否能得到可信结果
- 再用探针 prompt 判断 agent 是否真的执行了 Twinbox 命令
- 最后才回退到更激进的“显式执行命令”诊断路径

## 两类 Prompt 的角色

- **真实用户 prompt**：模拟真实提问方式，不暴露底层命令。它们决定“这个 skill 对真实用户好不好用”。
- **探针 prompt**：显式要求执行 `twinbox task ...` / `preflight`。它们不是日常用户话术，而是回归测试和故障定位手段。

原则：

- 验收时优先看真实用户 prompt
- 如果真实用户 prompt 表现异常，再用探针 prompt 判断是“没跑命令”还是“命令本身结果不对”

当前已知边界：

- UI 上可能出现**只有一句**「让我查找 weekly brief / twinbox 产物目录」然后**没有数据**：根因通常是模型**没有在同一轮里直接运行 `twinbox task …`**，而是先去 workspace 里“找路径”。**立刻补救**：发一条明确要求执行的探针（见下方「空转补救」）。
- `agent:twinbox:main` 曾成功命中过自然话术 -> `twinbox task latest-mail --json`
- 但 2026-03-25 后续复测里，同一主会话上的自然话术也出现过 `turn completed` 但 `assistant.content=[]` 的空响应
- 当前 OpenClaw 2026.3.23 本机路由下，`--session-id` 与 `--to` 也可能继续回落到 `agent:twinbox:main`，不能把它们当成稳定的新会话隔离手段
- 改走 `cron + isolated session` 后，显式探针可以稳定执行 `twinbox task ...` 并正常返回正文
- 但自然话术在 isolated session 中仍可能只读 `SKILL.md` / memory，最终空响应；因此它不是单纯的主会话污染问题
- 2026-03-27 确认：OpenClaw 只把 skill `description` 注入 system prompt；`SKILL.md` body 要靠 agent 主动 read 才能看到。对 `xfyun-mass` / `astron-code-latest`，generic `exec` 后模型可能立刻 stop，返回 `payloads=[]` 或只剩一句「让我执行命令：」。
- `onboarding start|status|next` 是当前最明显的受害路径：OpenClaw 还没有 `twinbox_onboarding_*` 原生工具，所以这几步只能走 generic `exec`。验收时默认把“新 session + bootstrap”当成**已知绕过法**，而不是继续追问 prompt 文案。
- 所以真实用户 prompt 目前仍应继续测，但验收记录里要单独标明“自然话术结果”与“平台空响应问题”两类证据

## Control UI 完全空白（连 P0a 探针都没有字）

若浏览器里 **Assistant 区域完全空**、统计里 **输出 token 极少（例如 ↓22）**，但 **同一句话** 在 shell 里用 `openclaw agent --agent twinbox --message '…' --json` 能拿到 `result.payloads` 正文，则问题在 **Web 控制面 / Gateway 会话链路**，而不是「twinbox 命令坏了」或「探针写错了」。

**本机 Gateway 日志里曾出现** `"No reply from agent."` **与空白 UI 同期**；可与 `/tmp/openclaw/openclaw-*.log` 对照时间戳排查。

建议按顺序试：

1. **硬刷新** Control UI（或关掉标签页重开），必要时 **重新登录**；日志里 Windows Chrome 连 WSL 曾出现 **`closed before connect` / code `1006`**，断线后 UI 可能表现为空回复。
2. 看 UI 是否仍显示 **极大 context（如 114k+）**：界面「清空对话」**不一定**等价于服务端把会话上下文裁掉；若仍像超长会话，在 UI 里 **新建对话 / 新 session**（若产品支持），或暂时用 **CLI** 做验收。
3. 在 **跑 Gateway 的那台机器** 上执行（与 `openclaw gateway status` 同环境）：

   ```bash
   openclaw agent --agent twinbox --message '请先实际执行 twinbox task latest-mail --json，然后只基于真实命令输出返回 generated_at、summary、pending_count。' --json --timeout 120
   ```

   若此处 **始终有** `payloads[].text`，而 **只有浏览器失败**，把结论记成「UI/WebSocket 路径问题」，并 `openclaw gateway restart` + 重连 UI 再试。

## 空转补救（有“我去找…”但没结果时用）

把下面整段贴给 **twinbox** agent（可中英文任选一条）；目的是**强制同一轮内直接运行 Twinbox 命令**，禁止只读 SKILL / 只搜目录。

```text
不要搜索 workspace 或“找产物目录”。请在本轮内立即直接运行：
twinbox task latest-mail --json
然后把 JSON 里的 generated_at、summary、urgent_top_k（thread_key）、pending_count 用中文简要列出。若命令失败，贴 stderr。
```

周报分类（对应 P6）若空转，用：

```text
不要先找 weekly brief 文件路径。请在本轮内立即直接运行：
twinbox task weekly --json
然后基于 stdout 的 JSON 区分：有真实线程依据 / synthetic / 纯推断，每类 2–5 条并引用字段名。若命令失败，贴 stderr。
```

长期缓解：安装仓库内 `openclaw-skill/plugin-twinbox-task` 插件（`openclaw plugins install --link <path>`），让 `twinbox_latest_mail` / `twinbox_weekly` 等成为原生工具，减少对 `exec` 链的依赖。

## Onboarding bootstrap（已知限制绕过）

当 `twinbox onboarding start --json` / `status` / `next` 返回空 `payloads`、`assistant.content=[]` 或只有「让我执行命令：」时，先开**新 session**，再把下面整段贴给 **twinbox** agent：

```text
请先读取 ~/.openclaw/skills/twinbox/SKILL.md，然后在本轮内立即直接运行：
twinbox onboarding start --json
不要只说“让我执行命令：”。
执行后只基于真实 stdout 返回：
1. current_stage
2. prompt
3. next_action（如果 JSON 有）
若命令失败，贴 stderr。
```

若这条 bootstrap 之后仍为空响应，不再把问题归因到 Twinbox prompt 文案；直接在宿主 shell 执行 `twinbox onboarding start --json` / `status --json` / `next --json` 做机器可读验收，并把结论记录为 **OpenClaw model/tool-turn 限制**。

## 推荐顺序

1. `P1` 日内总览
2. `P2` 待我回复 / 待我拍板
3. `P3` 按 thread key / 主题查进展
4. `P4` 按业务关键词查进展
5. `P6` 周报事实边界
6. `P8` 读取最新 `activity-pulse.json`
7. `P0a` / `P0b` / `P0c` / `P0d` 探针式验证 task 路由
8. `P7` 显式执行 `preflight`

说明：

- `P1`~`P6` 是更接近真实用户的主验证面
- `P0a`~`P0d` 与 `P7` 属于诊断型 prompt，不应被当成真实用户标准话术

## 自动化 / Gateway + `twinbox` agent（`openclaw agent`）

手工多轮可在 **OpenClaw 控制面** 或任何连同一 Gateway 的客户端里做；**批量、可重复**验收请用仓库脚本（直连 Gateway，与 **`openclaw agent --agent twinbox`** 同一路径）：

```bash
# 仓库根目录
python3 scripts/run_openclaw_prompt_tests.py
# 可选：OPENCLAW_BIN=openclaw AGENT_TIMEOUT=180 AGENT_THINKING=off
```

脚本行为要点：

- 顺序与上表一致：`P1`→`P6` 后换**新会话**再跑 `P8`→`P0a`~`P0d`→`P7`，减轻单会话过长导致后半段 **空 `payloads`**（长会话 + Gateway/控制面交付链上均可能出现）。
- 每段开头有一条 **bootstrap** 契约消息；自然话术段与探针段各一条。
- 单条失败会按类型自动重试（加强制“直接运行命令”提示）；仍失败则脚本以非零退出。

## P0a 显式执行 Latest Mail（探针）

```text
请先实际执行 `twinbox task latest-mail --json`，然后只基于真实命令输出返回：
1. generated_at
2. summary
3. urgent_top_k 的 thread_key 列表
4. pending_count
如果你没有实际执行成功，不要猜。
```

通过标准：

- 明确体现命令真实输出，而不是只复述 `SKILL.md`
- 至少给出 `generated_at`、`summary`、`urgent_top_k`、`pending_count`

## P0b 显式执行 Todo（探针）

```text
请先实际执行 `twinbox task todo --json`，然后只基于真实命令输出返回：
1. pending_count
2. urgent_count（如果有）
3. 前 3 个需要我处理的 thread_key
如果你没有实际执行成功，不要猜。
```

通过标准：

- 明确体现命令真实输出，而不是只复述 `SKILL.md`
- 至少给出 `pending_count` 和 1-3 个具体线程

## P0c 显式执行 Progress（探针）

```text
请先实际执行 `twinbox task progress tjnlzx_v1.5.0版本升级资源申请 --json`，然后只基于真实命令输出返回：
1. thread_key
2. latest_subject
3. waiting_on
4. stage
5. summary（如果 JSON 没有 summary，就明确说明是从 why 提炼）
如果你没有实际执行成功，不要猜。
```

通过标准：

- 能命中目标线程或明确列出最相关候选
- 输出字段来自真实 JSON，而不是凭主题脑补

## P0d 显式执行 Mailbox Status（探针）

```text
请先实际执行 `twinbox task mailbox-status --json`，然后只基于真实命令输出返回：
1. status
2. login_stage
3. error_code
4. actionable_hint
如果你没有实际执行成功，不要猜。
```

通过标准：

- 给出真实 preflight 字段，而不是只说“看起来已经就绪/缺少 env”
- 如果命令执行失败，必须原样说明失败原因

## P8 读取最新 Pulse

```text
请实际读取 runtime/validation/phase-4/activity-pulse.json，并只返回：
generated_at
summary
urgent_top_k 的 thread_key 列表
pending_count
不要做额外解释。
```

通过标准：

- 输出应与文件内容一一对应
- 如果只给概述、不贴字段值，视为失败

## P1 日内总览

```text
请基于 Twinbox 当前最新产物，告诉我今天最值得关注的 3 个线程。
要求：
1. 只使用最新的 activity-pulse / daily-urgent / pending-replies 相关产物
2. 每个线程给出：thread_key、为什么值得关注、最新进展时间
3. 不要泛泛总结，不要编造邮件内容
```

通过标准：

- 能给出 3 条具体线程
- 理由接近 `activity-pulse.json` 的 `urgent_top_k`
- 不混入周报式空话

## P2 待我回复 / 待我拍板

```text
请只看 Twinbox 当前最新日内产物，告诉我：
1. 哪些线程现在更像“待我回复”
2. 哪些线程更像“待我拍板”
3. 每类最多列 3 条，并说明依据
如果当前证据不足，请明确说证据不足。
```

通过标准：

- 会区分“证据足够”和“证据不足”
- 不把所有 urgent 都硬说成待我回复

## P3 按 Thread 查询进展

```text
帮我看下“aq01-tj0s1z-szpt（二期-2025）”这个事情现在进展如何。
要求：
1. 优先按 thread key / 主题匹配
2. 返回最新主题、最新活动时间、当前 why、waiting_on、queue_tags
3. 如果没有精确命中，再说明最接近的候选
```

通过标准：

- 能命中具体线程
- 输出结构接近 `thread progress QUERY`

## P4 按业务关键词查进展

```text
帮我查“北京云平台部署资源申请”现在进展如何。
要求：
1. 允许按业务关键词匹配，不要求完全等于主题
2. 返回最相关的 1-3 个线程
3. 每个线程说明匹配原因和当前状态
```

通过标准：

- 能按关键词命中，不只会按完整主题
- 会说明为什么匹配到这个线程

## P5 验证不重复推送语义

```text
请读取最新 activity-pulse，并解释：
1. 当前 urgent_top_k 为什么是这几条
2. 哪些是新出现的，哪些只是仍然处于关注状态
3. 当前去重语义是什么，什么情况下同一线程不会再次进入推送
```

通过标准：

- 能说清“线程级去重，不是下一轮一定 0 条”
- 不把 bridge 去重和 thread 去重混为一谈

## P6 周报事实边界

```text
请审查当前 weekly brief 里的内容，区分三类：
1. 有真实邮件或真实线程依据的内容
2. 来自 synthetic material sample 的内容
3. 只是建议或推断的内容
每类给 2-5 条，尽量引用来源文件名或字段名。
```

通过标准：

- 能识别 synthetic material
- 不把合成台账直接当真实事实

## P7 显式执行 Preflight

```text
请先实际执行 `twinbox mailbox preflight --json`，然后把原始 JSON 结果原样贴出来，再用一句话总结当前状态。
如果你没有实际执行成功，不要猜。
```

通过标准：

- 必须给出真实 JSON
- 如果只给口头总结、没有 JSON，视为失败
