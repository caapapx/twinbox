# OpenClaw Prompt Test

用于手工验证当前 OpenClaw + Twinbox 集成面的 prompt 集。

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

- `agent:twinbox:main` 曾成功命中过自然话术 -> `twinbox task latest-mail --json`
- 但 2026-03-25 后续复测里，同一主会话上的自然话术也出现过 `turn completed` 但 `assistant.content=[]` 的空响应
- 当前 OpenClaw 2026.3.23 本机路由下，`--session-id` 与 `--to` 也可能继续回落到 `agent:twinbox:main`，不能把它们当成稳定的新会话隔离手段
- 所以真实用户 prompt 目前仍应继续测，但验收记录里要单独标明“自然话术结果”与“平台空响应问题”两类证据

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
