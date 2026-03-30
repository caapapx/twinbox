
  # Twinbox OpenClaw Push / Bridge Reliability And Vendor-Safe Onboarding

  ## Summary

  把 Twinbox 在 OpenClaw 上的“宿主接线、后台调度、二阶段推送确认、日间/周报自动推送”收成一个真正可交付的闭环，默认适配 CLI+vendor/no-clone。

  最终产品目标：

  - twinbox onboard openclaw 成为默认的一键路径，不只是写 openclaw.json 和同步 SKILL.md，还必须把 OpenClaw tools/plugin 接线 + vendor-safe bridge timer 安装与健康
    检查 一并做完。
  - 只有宿主前置条件全部成功，才允许 handoff 到 Phase 2 对话 onboarding；否则不能进入 push_subscription。
  - push_subscription 从占位 prompt 改成“显式确认型”阶段：用户确认后，系统才真正写 subscription、启用对应 cadence、并返回可验证的结果。
  - 推送能力拆成两条：
      - daily push：基于 daytime-sync 的当前行动面
      - weekly push：基于 friday-weekly 的完整 weekly brief
  - 日间与周报推送要可分别关闭，不再是单一总开关。
  - 在 CLI+vendor/no-clone 模式下，宿主 bridge 只能依赖单一已安装 twinbox 入口，不能依赖 repo scripts/ 或把 twinbox-orchestrate 当作生产前提。

  ### 先纠偏：当前实现里最关键的不准确点

  1. 现在的 push_subscription 只是 onboarding 文案阶段，不会真正 push subscribe、不会 schedule enable、也不会校验 bridge。
  2. 现在的 twinbox deploy/openboard openclaw 不会自动安装或启用 twinbox-openclaw-bridge.timer。
  3. 现在 bridge systemd 单元依赖 repo scripts/twinbox_openclaw_bridge_poll.sh 和 TWINBOX_CODE_ROOT，与 vendor/no-clone 模式冲突。
  4. 现在自动推送只覆盖 daytime-sync -> notify_payload.summary，没有 weekly auto-push，也没有独立 daily/weekly toggle。
  5. 现在 push-subscriptions.json 只有单一 enabled 语义，没有 cadence 维度，没有 schedule ownership，没有 per-session backlog/fairness 状态。
  6. 现在 OpenClaw 里 onboarding start/status/next 没有原生 tool，后半段主要走 generic exec，已知会在 xfyun-mass / astron-code-latest 上出现 payloads=[]、
     assistant.content=[] 或只剩“让我执行命令：”。

  ## Product Decisions Already Locked

  以下产品决策视为已定，不再重新讨论：

  - bridge timer 是 hard requirement，不是可选增强。
  - twinbox onboard openclaw 必须默认一并完成：
      - OpenClaw tools/plugin 接线
      - vendor-safe bridge install
      - enable/start timer
      - bridge health check
      - 成功后才 handoff 到二阶段 onboarding
  - 二阶段首次 push onboarding 默认 daily=on、weekly=on，之后允许分别关闭。
  - daily push payload：summary + 最多 3 条线程 + overflow count
  - daily push 默认节奏：开启时默认改成 hourly
  - duplicate 语义：同线程 fingerprint 变化后重新入队
  - push signal source：urgent + pending
  - overflow handling：只显示前 3 条 + remaining count
  - 窗口语义：since last successful push
  - fairness：用 backlog 防止低排序项长期饿死
  - weekly push 纳入同一方案，不单独后置
  - weekly push 内容：完整渲染后的 weekly brief
  - weekly trigger：任意成功的 friday-weekly run 都触发自动推送，包括手动 rerun
  - enabling push 时也要确保 weekly-refresh 可用
  - disable granularity：必须支持 daily / weekly 分别关闭
  - schedule ownership：只要还有任一 subscription 需要某 cadence，对应 schedule 就必须保持启用
  - CLI+vendor/no-clone 模式下，bridge systemd 绑定 单一已安装 twinbox 入口，不绑定 repo script，不依赖 twinbox-orchestrate

  ## Implementation Changes

  ### 1. Reframe twinbox onboard openclaw as full host prerequisite setup

  把 twinbox onboard openclaw 明确定义为“两阶段总向导”的第一阶段，职责是把 Phase 2 push 所需宿主条件全部准备好，而不是只做部分接线。

  新的宿主态默认顺序：

  1. 校验 openclaw、state root、mailbox/LLM 最低门槛。
  2. 执行 roots/init。
  3. 合并 openclaw.json。
  4. 导入并校验 Twinbox OpenClaw plugin/tools。
  5. 安装 vendor-safe bridge user units。
  6. systemctl --user daemon-reload
  7. enable/start bridge timer
  8. 执行 bridge health check
  9. openclaw gateway restart
  10. 只有以上全部成功，才输出二阶段 handoff。

  强约束：

  - onboard openclaw 默认不能把 bridge 安装留给文档手工步骤。
  - onboard openclaw 默认不能在 tools/plugin 未就绪时 handoff 到 Phase 2。
  - 若宿主接线未完成，Phase 2 不得显示“可配置推送”的假完成状态。

  和 deploy openclaw 的关系：

  - deploy openclaw 保留为高级/脚本化入口。
  - deploy openclaw 与 onboard openclaw 必须共享同一套宿主接线实现。
  - 任何 bridge/tool/plugin 变更都只允许有一套实现，避免两个入口行为漂移。

  高级逃生口可以保留，但必须显式：

  - 如需跳过 bridge，只允许高级入口显式传 --skip-bridge 或同类参数。
  - 默认行为绝不跳过。

  ### 2. Make bridge vendor-safe and stop depending on repo scripts

  当前 bridge installer/service/timer 全部依赖 repo scripts/，必须重做为 vendor-safe。

  目标形态：

  - systemd bridge 只依赖单一已安装 twinbox 二进制。
  - 不再依赖：
      - TWINBOX_CODE_ROOT/scripts/twinbox_openclaw_bridge_poll.sh
      - repo checkout
      - integrations/openclaw/*.service 软链回仓库
  - twinbox-orchestrate 可以继续存在，但不能是 vendor/no-clone 宿主的可靠性前提。

  新增稳定入口，收敛到 twinbox：

  - twinbox host bridge poll
  - twinbox host bridge status
  - twinbox host bridge install
  - twinbox host bridge remove

  具体要求：

  - twinbox host bridge poll 内部调用现有 bridge-poll 编排逻辑。
  - twinbox host bridge install 负责：
      - 解析 twinbox 绝对路径
      - 生成真实 unit 文件到 ~/.config/systemd/user/
      - 写 env/config/status 文件
      - daemon-reload
      - enable/start timer（除非显式 no-start）
  - unit 的 ExecStart 必须直接调用已安装 twinbox 的绝对路径，例如：
      - ... /abs/path/to/twinbox host bridge poll --format json
  - unit 不得再引用 repo 模板里的 shell wrapper。
  - status 命令需要返回：
      - unit file path
      - timer enabled/active
      - last poll status
      - last successful poll time
      - openclaw binary path
      - twinbox binary path
      - 当前 state root

  rollback 对称性：

  - deploy openclaw --rollback 或 twinbox host bridge remove 需要：
      - stop/disable timer
      - 删除 Twinbox bridge 相关 unit/env/status 文件
      - 不误删其他 OpenClaw/Twinbox 数据

  ### 3. Treat tool import and bridge install as one prerequisite bundle

  不能把“导入 OpenClaw tools/plugin”与“bridge timer 安装”拆成两个松散步骤。对产品来说，它们属于同一组 Phase 2 push 的宿主前置条件。

  因此宿主 prerequisite bundle 必须一体返回状态：

  - plugin/tool loaded
  - bridge installed
  - timer enabled
  - timer active
  - bridge health check passed
  - gateway restarted after tool sync

  如果其中任意一项失败：

  - onboard openclaw 返回失败
  - 不 handoff 到 Phase 2
  - JSON report 中明确是哪一步失败

  ### 4. Add native OpenClaw onboarding tools for the Phase 2 path

  当前 mailbox_setup 和 config_set_llm 已有 plugin tools，但 onboarding start/status/next 没有。这是 OpenClaw 上二阶段不稳定的根因之一。

  需要新增原生 tools，至少包括：

  - twinbox_onboarding_start
  - twinbox_onboarding_status
  - twinbox_onboarding_advance
  - twinbox_onboarding_confirm_push

  职责划分：

  - twinbox_onboarding_start
      - 返回当前 stage、prompt、阶段元信息
  - twinbox_onboarding_status
      - 返回已完成阶段、当前阶段、剩余阶段、关键环境 readiness
  - twinbox_onboarding_advance
      - 用于推进非 push 阶段
      - 支持现有 profile_notes、calibration_notes、cc_downweight
  - twinbox_onboarding_confirm_push
      - 专门负责 push_subscription 阶段的事务性提交
      - 输入 daily/weekly 用户选择、session target
      - 校验 bridge readiness
      - 写 subscription
      - 计算并同步 schedule ownership
      - 成功后推进 onboarding 到 completed
      - 返回完整 JSON 结果

  OpenClaw 内的 happy path 必须改为：

  - mailbox_login 用 twinbox_mailbox_setup
  - llm_setup 用 twinbox_config_set_llm
  - profile/material/routing 用 onboarding native tools 推进
  - push_subscription 用 twinbox_onboarding_confirm_push

  这样二阶段就不再依赖 generic exec twinbox onboarding next --json 才能完成关键阶段。

  CLI fallback 仍保留：

  - twinbox onboarding start/status/next --json 继续保留，供宿主 shell、测试、fallback 验收使用。
  - 但 OpenClaw 会话内不再把它当主要路径。

  ### 5. Redesign push subscription data model around cadences

  当前 push-subscriptions.json 过于扁平，需要升级为支持 cadence、ownership、dedupe、backlog 的结构。

  目标能力：

  - 同一个 session target 可独立控制 daily / weekly
  - 每个 cadence 有自己的发送状态
  - daily 可以维护 backlog/fairness
  - weekly 可以维护 last_run_id
  - subscription 与 global schedule enable/disable 之间有明确 ownership 关系

  建议的数据形状：

  - 顶层按 session_target 唯一
  - 每条 subscription 包含：
      - session_target
      - enabled
      - created_at
      - cadences.daily.enabled
      - cadences.weekly.enabled
      - delivery_state.daily.last_successful_push_at
      - delivery_state.daily.backlog
      - delivery_state.daily.delivered_fingerprints
      - delivery_state.weekly.last_run_id
      - filters（保留扩展位，但本次不做复杂策略）
  - 当前的 session_id 命名要改为更准确的 session_target 或等价名字，避免把瞬时 transcript/session id 当长期订阅主键。

  兼容迁移：

  - 旧订阅文件首次读取时自动迁移
  - 旧 push subscribe 语义默认等价于：
      - daily=on
      - weekly=on
  - 旧 push unsubscribe 语义默认等价于：
      - daily=off
      - weekly=off

  新增/调整 CLI：

  - twinbox push configure SESSION_TARGET --daily on|off --weekly on|off --json
  - twinbox push list --json 输出 cadence-aware 结构
  - 保留兼容的 push subscribe/unsubscribe

  ### 6. Add schedule ownership and cadence-aware enable/disable logic

  当前 schedule enable/disable 是 job 级别的，和 subscription 没有关联。需要补一层 ownership 逻辑。

  必须满足：

  - 只要存在任一 active daily subscription，就必须保持 daily-refresh enabled。
  - 只要存在任一 active weekly subscription，就必须保持 weekly-refresh enabled。
  - 关闭某个 session 的 daily，不得误关其他 session 还在依赖的 daily-refresh。
  - 关闭某个 session 的 weekly，不得误关其他 session 还在依赖的 weekly-refresh。

  日间 hourly 默认：

  - 当用户首次开启 daily push，且当前没有显式 runtime override 时：
      - 自动为 daily-refresh 写入 hourly override
  - 如果已有显式 override：
      - 保留现有 cron
      - 不擅自覆盖共享实例配置

  需要新增一个 ownership 计算层，输入：

  - 所有 subscription 的 cadence 开关
  - 当前 schedule override 状态

  输出：

  - 对应 cadence 是否应启用
  - 是否需要创建/保留/删除 OpenClaw cron job
  - 是否需要落默认 hourly override

  ### 7. Define daily push semantics precisely

  daily push 必须与当前代码中 daytime-sync/activity-pulse 的“当前行动面”保持一致，不要混进 weekly 统计维度。

  daily push 的信号源：

  - 基于 daytime-sync 后生成的 activity-pulse
  - 优先看 urgent + pending 当前行动面
  - 不做“整天全量累计推送”的产品承诺

  值得推送的判断：

  - 当前进入 urgent / pending 行动面，且对用户可见
  - 或线程 fingerprint 发生变化后重新进入 notifiable
  - 已 completed/dismissed 的线程不再进入可推送队列，除非重新激活条件满足

  重复判断：

  - 同线程 fingerprint 不变，不重复推送
  - 同线程 fingerprint 变化，重新入队
  - dismissed / completed 与 fingerprint 反应逻辑沿用现有 user_queue_state 语义

  单次规模：

  - 最多推 3 条线程
  - 文本中附带 remaining count
  - 超出的线程进入该 session 的 daily backlog

  公平性：

  - backlog 必须参与轮转
  - 不能永远只把分数最高的 3 条发给用户，导致低排序项长期见不到

  窗口语义：

  - daily push 视图和“新内容”判断以 since last successful push 为准
  - 若上次发送失败，不推进这个时间点

  push 文本固定为：

  - 一行 summary
  - 最多 3 条线程，每条有 thread_key + why/维度摘要
  - 如有溢出，显示 还有 N 条

  ### 8. Add weekly auto-push as first-class behavior

  weekly push 需要正式接入，不再停留在“用户手动看周报”。

  weekly trigger：

  - 任意成功的 friday-weekly run 都触发 weekly auto-push
  - 包括手动 rerun

  weekly 内容：

  - 发完整渲染后的 weekly brief Markdown
  - 不缩成简版 summary
  - 不混成 daily 风格的 3 条摘要

  weekly dedupe：

  - 用 run_id 去重
  - 同一个 run_id 不重复推
  - 手动 rerun 生成新 run_id，允许再次推送

  和 daily 的关系：

  - daily / weekly 是两个独立 cadence
  - daily 关闭时 weekly 可继续开
  - weekly 关闭时 daily 可继续开

  ### 9. Update orchestration so push dispatch is cadence-aware

  当前 run_scheduled_job 只在 daytime-sync 成功后触发 dispatch_push。需要扩展为 cadence-aware dispatch。

  目标行为：

  - daytime-sync 成功后：
      - 对启用 daily 的 subscriptions 走 daily dispatch
  - friday-weekly 成功后：
      - 对启用 weekly 的 subscriptions 走 weekly dispatch
  - dispatch 结果都写入：
      - schedule 返回 payload
      - runtime/audit/schedule-runs.jsonl

  日志内容要能区分：

  - push_dispatch.daily
  - push_dispatch.weekly
  - sent / failed / skipped
  - skipped 原因（例如 no active subscriptions / no notifiable items / duplicate run_id）

  ### 10. Extend deploy/onboard reports so readiness is machine-verifiable

  当前 deploy report 里只有通用 step 列表。需要把 push 相关前置条件显式暴露出来。

  deploy openclaw --json / onboard openclaw --json 至少返回：

  - plugin_tools.status
  - plugin_tools.loaded_names
  - bridge.status
  - bridge.timer_enabled
  - bridge.timer_active
  - bridge.last_health_check
  - bridge.twinbox_bin
  - bridge.openclaw_bin
  - phase2_ready

  phase2_ready 的定义必须明确：

  - 只有当 tools/plugin + bridge timer + health check 都成功时才为 true

  ### 11. Documentation and skill synchronization

  这次改动会同时影响 CLI、OpenClaw tool、onboarding 行为、bridge 安装路径，所以必须同步更新文档和 skill。

  必须更新：

  - 仓库根 SKILL.md
  - .agents/skills/twinbox/SKILL.md
  - OpenClaw deploy docs
  - docs/ref/openclaw-deploy-model.md
  - docs/ref/orchestration.md
  - docs/ref/scheduling.md
  - docs/ref/cli.md
  - 如涉及 plugin tool 变更，同步更新 plugin 文档

  文档中要明确写清：

  - onboard openclaw 默认会安装并校验 bridge，不再是“可选 §3.9”
  - CLI+vendor/no-clone 不依赖 repo scripts
  - daily push 和 weekly push 的内容与触发边界不同
  - push_subscription 不再只是提示语阶段，而是显式配置阶段

  因为会改 CLI 和 plugin tool：

  - 必须同步更新 tool 注册文件
  - 必须执行 openclaw gateway restart

  ## Public APIs / Interfaces / Types To Add Or Change

  ### CLI

  新增或调整：

  - twinbox host bridge poll
  - twinbox host bridge status
  - twinbox host bridge install
  - twinbox host bridge remove
  - twinbox push configure SESSION_TARGET --daily on|off --weekly on|off --json
  - 保留兼容：
      - twinbox push subscribe
      - twinbox push unsubscribe

  可选但建议：

  - twinbox onboard openclaw --skip-bridge
  - twinbox deploy openclaw --skip-bridge
  - twinbox deploy openclaw --rollback 同时处理 bridge remove

  ### OpenClaw plugin tools

  新增：

  - twinbox_onboarding_start
  - twinbox_onboarding_status
  - twinbox_onboarding_advance
  - twinbox_onboarding_confirm_push

  现有工具继续保留：

  - twinbox_mailbox_setup
  - twinbox_config_set_llm
  - twinbox_schedule_enable/disable/list/update/reset

  ### Subscription storage

  升级 runtime/push-subscriptions.json 结构为 cadence-aware schema，并支持旧版自动迁移。

  ### Deploy/onboard JSON report

  新增 bridge/plugin readiness 字段，暴露 phase2_ready。

  ## Test Cases And Scenarios

  ### Host bridge / vendor-safe runtime

  - 在没有 repo checkout、只有 installed twinbox + vendor 的宿主上：
      - twinbox host bridge install --json 成功
      - 生成的 systemd unit 不引用 repo scripts/
      - twinbox host bridge poll --dry-run --format json 可执行
  - twinbox deploy openclaw --json 会自动包含 bridge install/status 步骤
  - twinbox onboard openclaw --json 在 bridge 失败时不 handoff Phase 2
  - rollback 会 stop/disable/remove Twinbox bridge unit

  ### OpenClaw plugin/tools

  - plugin tools 导入成功后，onboard openclaw JSON report 反映 loaded names
  - twinbox_onboarding_start/status/advance/confirm_push 都能在 OpenClaw 中走通，不依赖 generic exec
  - push_subscription 阶段在 OpenClaw 中能完成：
      - daily+weekly 默认开启
      - 单独 daily off
      - 单独 weekly off
      - 全关
  - confirm_push 返回中包含：
      - completed_stage
      - current_stage
      - bridge_status
      - daily enabled/disabled
      - weekly enabled/disabled
      - ownership/schedule status

  ### Subscription migration and cadence ownership

  - 旧订阅文件能自动迁移为新 schema
  - 两个 session 同时启用 daily 时，关闭其中一个不会误关 daily-refresh
  - 最后一个 daily owner 关闭后，daily-refresh 才可 disable
  - weekly-refresh 同理

  ### Daily push behavior

  - unchanged fingerprint 不重复推送
  - changed fingerprint 重新入队
  - 单次最多发 3 条并有 remaining count
  - backlog 跨多轮轮转，不饿死低排序项
  - dismissed/completed 线程不再重复出现在 backlog
  - last_successful_push_at 只在发送成功时推进
  - 无 notifiable items 时：
      - 不发消息
      - 返回 skipped reason

  ### Weekly push behavior

  - 成功的 friday-weekly run 会自动推送完整 weekly brief
  - 同一 run_id 不重复发送
  - 手动 rerun 因新 run_id 可再次发送
  - weekly disabled 的 session 不接收 weekly 消息

  ### Regression

  - daytime-sync 现有 activity-pulse 生成不回归
  - queue dismiss/complete/restore 与 fingerprint reactivation 逻辑不回归
  - twinbox schedule list/update/enable/disable/reset 保持兼容
  - twinbox onboarding next --json 的宿主 shell fallback 仍可用
  - 现有 mailbox_setup、config_set_llm tools 不回归

  ## Assumptions And Defaults

  - 默认用户路径是 twinbox onboard openclaw，不是手工跑 deploy + 自己补 bridge。
  - twinbox onboard openclaw 必须把 tools/plugin 接线 + bridge install + health check 视为同一个 prerequisite bundle。
  - phase2_ready=true 是 handoff 到二阶段的唯一条件。
  - bridge 在 vendor/no-clone 模式下只依赖单一已安装 twinbox 二进制。
  - twinbox-orchestrate 继续保留给开发/兼容，但不是生产 bridge 的安装前提。
  - 第一次开启 daily push 时，若没有已有 runtime override，则自动把 daily-refresh 设为 hourly；若已有 override，则尊重现状。
  - daily push 是“当前行动面通知”，不是“整天累计所有历史项”的严格承诺。
  - weekly push 是“完整周报投递”，不是 daily 的放大版。
  - OpenClaw 当前 generic exec 在 onboarding 后半段不可靠，这次方案默认以 native plugin tools 绕开，而不是继续依赖 bootstrap workaround。

  ## Execution Guidance For The Next Session

  新对话进入实现时，不要重新做产品决策，只做必要的代码级确认与落地。实现顺序建议：

  1. 先做 vendor-safe bridge 单一入口与 installer/status/remove
  2. 再把 deploy/onboard 接到同一套 prerequisite bundle
  3. 再补 plugin onboarding native tools
  4. 再升级 subscription schema 和 cadence ownership
  5. 最后接 daily/weekly dispatch、文档、SKILL、gateway restart

  若发现 OpenClaw 当前 plugin runtime 无法稳定拿到当前 session target，再补一个最小 session resolve 工具，但这属于实现细节确认，不是产品层重新决策。