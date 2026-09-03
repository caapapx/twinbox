# Twinbox 自我进化矫正任务

> **权威契约**：[`specs/002-analysis-correctness/`](specs/002-analysis-correctness/spec.md)。本文是 2026-09-03 事故复盘的历史输入，冲突以 spec/plan/tasks 为准。实现走 `/speckit-implement`，不要把本文当第二份需求源。

你是负责维护本仓库 Twinbox 邮件 MCP 服务的 Code Agent。
本任务来自一次真实使用事故复盘：2026-09-03（Asia/Shanghai），agent 查询「今天下午必须处理的邮件」时，暴露出一批正确性与可用性缺陷。

## 仓库与架构

- **代码根**：当前 git 仓库（`twinbox_core/` + 根目录 `mcp-server.mjs`）
- **状态根**：`~/.twinbox`（或环境变量 `TWINBOX_STATE_ROOT`）
  - `runtime/context/phase1-context.json`（envelopes + sampled_bodies）
  - `runtime/context/uid-watermarks.json`
  - `runtime/validation/phase-1/raw/envelopes-merged.json`
  - `runtime/validation/phase-4/{activity-pulse.json, daily-urgent.yaml, pending-replies.yaml, sla-risks.yaml, weekly-brief-raw.json}`
- **数据流**：`fetch_incremental` → `run_analysis` → `build_activity_pulse`
- **约束**：
  - 对真实邮箱**只读**（禁止 send / move / delete / archive / flag）
  - MCP 工具名与入参 schema 不得破坏；现有 JSON 字段只能新增，不能删除/改名
  - 凭据不得出现在任何输出中
  - 默认不 commit / push；除非用户明确要求

## 必须修复的缺陷（按优先级，均附代码位置）

### P0-1 正文未做 MIME 解析，分析层在「盲猜」

- **位置**：`twinbox_core/imap_fetch.py::fetch_bodies_imap`
- **现状**：`BODY.PEEK[TEXT]` 原始字节按 `utf-8/replace` 解码；无 MIME 解析、无 charset（GB2312 乱码）、不剥离附件 base64；`max_chars=3000` 截在原始 MIME 上。
- **要求**：
  1. 用 `email.message_from_bytes` 解析 multipart；
  2. 优先 text/plain；无 plain 时 text/html → 纯文本（去标签/样式/内联图）；
  3. 正确处理 CTE（base64 / quoted-printable）与 charset（至少 utf-8、gb18030/gb2312、big5、latin-1；未知时 best-guess 并记 `decoded_with`）；
  4. 剥离附件/内联图内容，保留 `attachments: [{filename, content_type, size_bytes}]`（filename 解码 RFC2047）；
  5. 截断作用在「解码后纯文本」上（plain ≥ 3000 字符）。
- **验收**：构造 GB2312 + QP + base64 附件的 multipart 测试邮件；输出必须是可读中文纯文本 + 附件元数据；不得出现 QP `=` 残留或长 base64 串。

### P0-2 分析 prompt 正文预览只有 300 字符（且常为 MIME 样板）

- **位置**：`twinbox_core/analyze.py::_build_prompt`（`body_preview = ...[:300]`）
- **要求**：
  1. 每条预览 ≥ 800 字符（plain）；同一线程**最新一封**可放宽到 2000；
  2. prompt **按线程分组**（thread_key → 时间倒序邮件列表），标记 `is_latest=true`；当前是扁平 `envelopes[:100]`，LLM 只能靠主题猜线程；
  3. `SYSTEM_PROMPT` 追加硬规则：
     - 判定 `waiting_on_me` / pending **必须以 is_latest 邮件内容为准**；
     - 若最新邮件是审批人回复「同意/批准/收到/已处理」等 → 不得再判 waiting_on_me，应标 `resolved_by_reply`（新字段）；
     - 禁止「可能包含」「提示需我确认」等推测性 why；why 必须引用原文证据。
- **验收**（用 `~/.twinbox` 真实状态回放，复制一份再改）：
  - 「辽宁移动…白名单报备申请」不得再出现在 pending_replies（最新邮件是 weimin「同意」）；
  - 「【验收登记】AQ01-HZH0S-FYJ-2026」（正文含「请登记处理」）必须进入 pending_replies 或 daily_urgent。

### P0-3 queue 标签 join 大小写/前缀不一致 → 标签静默丢失

- **位置**：`twinbox_core/pulse.py::_queue_membership` + `build_activity_pulse`
- **根因**：LLM 写出的 `thread_key` 未归一化；pulse 侧 `_normalize_thread` 做了 lowercase、去 Re:/回复/转发/答复、去尾部 8 位日期。`queue_mem.get(tk)` 精确匹配 → 本次会话复盘中 pending 5 条丢 4 条。
- **要求**：
  1. 抽公共 `normalize_thread_key()`，join 两侧统一使用；
  2. 匹配失败不得静默：写入 `diagnostics.queue_join_misses: [thread_key...]`，并在 `twinbox_status` 可见。
- **验收**：回放后 pending_replies 全部正确 join 到 pulse（或进入 resolved），`queue_join_misses` 为空。

### P1-1 陈旧快照无告警；auto-sync 只认「缺失」

- **位置**：`mcp-server.mjs::needsSync`（仅当 `ok===false && recovery_tool==="twinbox_sync"`）
- **要求**：
  1. `latest_mail` / `todo` / `weekly` 输出新增 `staleness: {stale, age_hours, threshold_hours}`（阈值默认 4h，可配置）；
  2. `stale===true` 时 MCP 层自动 `sync --json`（复用 `latestMailWithAutoSync`），顶部加 `=== auto sync (pulse was stale, age=Xh) ===`；
  3. 自动同步失败 → 返回 `ok:false + recovery_tool`，禁止用旧数据装作成功。
- **验收**：把 `activity-pulse.json` 的 `generated_at`/mtime 回拨 2 天后调 `latest_mail`，必须自动同步；IMAP 不可达时必须失败而非旧数据。

### P1-2 sync 报告与阶段一致性

- **位置**：`twinbox_core/cli.py::cmd_sync`（当前无视 `run_analysis` 的 `ok:false`，仍返回整体 `ok:True`）
- **要求**：
  1. 分析失败时：整体不得伪装完全成功 → `ok:true` + `degraded:["analysis"]`，pulse 顶层 `stale_analysis:true`；
  2. sync 输出新增 `consistency: {context_generated_at, pulse_generated_at, watermark_last_sync_at, last_phase4_at, gaps:[...]}`；
  3. 文档化 `new_envelope_count`（= 本次新增入库信封数），新增 `watermark_range: "UID a→b"`。
- **验收**：人为制造「context 新于 pulse」时 `gaps` 非空；`twinbox_status` 暴露一致性字段。

### P1-3 extract 返回解码正文 + 附件元数据

- **位置**：`twinbox_core/extract.py::envelope_to_report`（`"body_text": str(env.get("body",""))`）
- **要求**：
  1. `body_text` = P0-1 解码纯文本（截断 5000 + `body_truncated: bool`）；
  2. 新增 `attachments: [{filename, content_type, size_bytes}]`；
  3. 输出不得出现 MIME 边界行或 base64 块；
  4. 可选 `from_hour` / `to_hour`（本地时区整数小时），支持「下午」过滤。
- **验收**：`extract since=2026-09-03 until=2026-09-04 from_hour=12`，body 可读、附件仅元数据、无 `Content-Type` MIME 残留。

### P2-1 sampled_bodies 两个 bug

- **位置**：`twinbox_core/imap_fetch.py::sample_bodies_imap`
- **现状**：
  1. `fetch_bodies_imap` 用 `folder#uid`，但 `out[uid]` 只用裸 UID → 多文件夹冲突；`analyze._build_prompt` 的 `body_map.get(mid)` 用 `env["id"]`；
  2. `envelopes[:sample_count]` 在 uid 升序批次上等于采**最旧** N 封。
- **要求**：key 统一 `folder#uid`；采样先按 date 倒序再取最新 N。
- **验收**：单元测试覆盖同 uid 跨文件夹不覆盖；50 封新邮件时样本含最新 30。

### P2-2 needs_attention 排序校准

- **位置**：`twinbox_core/pulse.py::build_activity_pulse`
- **现状**：`score = new*10 + urgent*40 + pending*30 + sla*20`；`attention = any queue_tags`，无时效衰减。
- **要求**：
  1. `last_activity_at` > 48h 且 `new_message_count==0` 的 sla_risk：score ×0.5 + `aging:true`；
  2. 顶层 `score_legend` 文档化公式；
  3. 可配置动作词表 `config/action-verbs.yaml`：最新正文命中强动作词且无标签 → `score += 15` + `queue_tags: ["action_hint"]`。
- **验收**：回放后 9/1 sla_risk 预警 score 低于带「请登记处理」的验收登记线程。

### P2-3 thread_inspect 返回最新正文

- **位置**：`twinbox_core/pulse.py::search_threads` / `cli.py` thread-inspect
- **要求**：每条结果附加 `latest_message: {from_name, date, body_text}`（截断 1500；无样本时 `body_unavailable:true`，字段不得省略）。

### P2-4 管道健康可见性

- **位置**：`config/schedules.yaml` + `cli.py::cmd_status`
- **要求**：`twinbox_status` 新增 `pipeline: {last_fetch_at, last_analysis_at, last_pulse_at, last_scheduled_run_expected_at, missed_runs:[...]}`；连续 ≥2 次 missed → `warnings`。

## 工作方式

1. **先复现，后动手**：只读复制 `~/.twinbox`（或 `TWINBOX_STATE_ROOT`）做回放，复现 P0-3（pending 丢标签）与 P0-2（验收登记无标签 / 辽宁误标 pending），复现结果写入提交说明或 `EVOLUTION.md`。
2. **向后兼容**：MCP 工具名、入参、现有 JSON 字段不变；新字段一律 additive。
3. 每个 P0/P1 至少 1 个回归测试放 `tests/`（pytest；构造邮件；**不**依赖真实 IMAP/LLM；LLM 用 mock）。
4. LLM prompt 改动：新旧 `SYSTEM_PROMPT` diff 写进 `EVOLUTION.md`。
5. 不修改凭据、不触碰真实邮箱写操作。
6. 完成后跑 `tests/mcp-smoke.mjs` 全绿，并写 `EVOLUTION.md`（改了哪些文件、为什么、回放前后对比）。

## Definition of Done

- [ ] 回放：pending_replies 无辽宁移动误标；【验收登记】FYJ-2026 进入 pending 或 daily_urgent；pending 全部正确 join 到 pulse
- [ ] `latest_mail` 在快照回拨 2 天时自动同步且带 `staleness`
- [ ] `extract`：body_text 可读、附件仅元数据、无 MIME 残留
- [ ] `twinbox_status` 显示 pipeline 各阶段时间与 missed_runs
- [ ] 新增测试 + mcp-smoke 通过
- [ ] `EVOLUTION.md` 已生成
