# Feature Specification: Analysis Correctness

**Feature Branch**: `002-analysis-correctness`

**Created**: 2026-09-03

**Status**: Draft（实现前冻结；git 主干是 `master`，本目录名不是 git 分支）

**Input**: User description: "纠正 Twinbox 分析与工具层：MIME 解码、按线程最新邮件判定 waiting_on、thread_key 归一化 join、过期快照自动同步、extract 返回可读正文、采样与 needs_attention 校准。历史输入见仓库根 `twinbox-evolution-prompt.md`。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 读到的正文是人话 (Priority: P1)

邮箱主人让 agent 看一封 GB2312 / quoted-printable / 带附件的邮件。工具返回解码后的中文纯文本和附件文件名，而不是 MIME 边界和 base64。分析层用同一套解码结果判定紧急与待回复。

**Why this priority**: 正文不可读时，后续所有分类都在猜。这是整次事故的根因。

**Independent Test**: 构造一封 multipart 测试邮件（GB2312 + QP + base64 附件），不连真实 IMAP，断言解码输出为可读中文且附件只有元数据。

**Acceptance Scenarios**:

1. **Given** 一封 GB2312 quoted-printable 的 multipart 邮件，**When** 抓取或抽取正文，**Then** `body_text` 是可读中文，不含 MIME 边界或长 base64。
2. **Given** 邮件含 XLSX/PNG 附件，**When** 返回抽取结果，**Then** 只有 `attachments[{filename, content_type, size_bytes}]`，不含附件内容。
3. **Given** 分析层构建 prompt，**When** 使用采样正文，**Then** 预览来自解码纯文本，而不是 MIME 样板的前 300 字符。

---

### User Story 2 - 待办跟最新一封走 (Priority: P1)

邮箱主人问「今天下午必须处理什么」。系统按线程分组，以最新一封为准：审批人已回复「同意」的申请不再标「待我审批」；正文写着「请登记处理」的新请求进入待办。

**Why this priority**: 错误的 waiting_on 会让 agent 催办已结束的事、漏掉真动作。

**Independent Test**: 回放复制的本地状态（不写真实邮箱）：辽宁白名单最新邮件为「同意」时不得出现在 pending；验收登记「请登记处理」必须进入 pending 或 daily_urgent。

**Acceptance Scenarios**:

1. **Given** 线程最新邮件是审批人「同意/批准/收到/已处理」，**When** 运行分析，**Then** 该线程不在 `pending_replies`，并在该线程记录上设置 `resolved_by_reply: true`（pulse 可投影为等价标签或字段）。
2. **Given** 线程最新邮件含明确动作（如「请登记处理」），**When** 运行分析，**Then** 该线程出现在 pending_replies 或 daily_urgent。
3. **Given** 分析 why 字段，**When** 检查措辞，**Then** 不出现「可能包含」「提示需我确认」等无原文依据的推测。

---

### User Story 3 - 分析标签全部看得到 (Priority: P1)

LLM 标出的 urgent / pending / sla 必须全部投影到 pulse 的 `queue_tags`。大小写、Re:/回复前缀、尾部日期不得导致静默丢标签。

**Why this priority**: 标签丢失会让 needs_attention 撒谎；用户只看见碰巧匹配的那一条。

**Independent Test**: 用已知 pending-replies 列表与 pulse 做 join；全部命中或进入 resolved；未命中写入可见 diagnostics。

**Acceptance Scenarios**:

1. **Given** pending-replies 有 N 条 thread_key（大小写/前缀与主题不一致），**When** 构建 activity pulse，**Then** 对应线程都带 pending（或已 resolved），`queue_join_misses` 为空。
2. **Given** 某条 LLM thread_key 无法归一化匹配任何线程，**When** 查看 pulse / status，**Then** 该 key 出现在 `diagnostics.queue_join_misses`，而不是消失。

---

### User Story 4 - 过期快照会刷新或失败 (Priority: P2)

邮箱主人问「今天的邮件」。若本地 pulse 超过新鲜度阈值，工具先同步再回答；同步失败则明确失败，不得把两天前的数据当成功结果。

**Why this priority**: 「auto-sync if missing」不等于「过期也当新鲜」。

**Independent Test**: 把 pulse 的 `generated_at` 回拨超过阈值后调用 latest_mail；IMAP 可达则自动同步，不可达则 ok=false。

**Acceptance Scenarios**:

1. **Given** pulse 存在但超过阈值（默认 4 小时），**When** 调用 `twinbox_latest_mail`，**Then** 先同步，输出含 staleness 且带自动同步说明。
2. **Given** pulse 过期且同步失败，**When** 调用 latest_mail，**Then** 返回失败与 recovery_tool，不返回旧快照装作成功。
3. **Given** 新鲜 pulse，**When** 调用 latest_mail / todo / weekly，**Then** `staleness.stale` 为 false。

---

### User Story 5 - 同步报告诚实、抽取可读 (Priority: P2)

同步失败分析时不得整体伪装成功。抽取支持本地时区小时过滤，返回解码正文。

**Why this priority**: 数字对不上会让 agent 误判「只来了 1 封」；extract 原始 MIME 浪费整轮对话。

**Independent Test**: 分析失败夹具使 sync 带 degraded；extract 对构造邮件无 MIME 残留。

**Acceptance Scenarios**:

1. **Given** LLM 分析失败，**When** sync 结束，**Then** 结果含 `degraded: ["analysis"]` 且 pulse 标 `stale_analysis`，不得仅 `ok: true` 且无降级标记。
2. **Given** 信封库与 pulse 时间差超过一个同步周期，**When** 查看 sync/status，**Then** `consistency.gaps` 非空。
3. **Given** extract 带 since/until 与 from_hour，**When** 返回报告，**Then** body_text 可读、可截断标记明确、无 MIME 残留。

---

### User Story 6 - 注意力列表与体检可用 (Priority: P3)

新的明确动作请求不低于过期 sla 预警。点开线程能看到最新正文。status 能看出管道哪一阶段多久没跑成功。

**Why this priority**: 排序与体检是校准，不阻塞前三条正确性。

**Independent Test**: 回放或构造：老化 sla_risk 分数低于带动作词的新请求；inspect 含 latest_message；status 含 pipeline 时间与 missed_runs。

**Acceptance Scenarios**:

1. **Given** sla_risk 线程超过 48h 无新邮件，**When** 生成 pulse，**Then** 其 score 降权并带 aging。
2. **Given** 最新正文命中可配置动作词且无 LLM 标签，**When** 生成 pulse，**Then** 获得 action_hint 与分数加成。
3. **Given** thread_inspect 命中线程，**When** 查看结果，**Then** 含 latest_message 或显式 `body_unavailable: true`。
4. **Given** 连续错过至少两次计划运行，**When** 调用 status，**Then** warnings 非空并列出 missed_runs。

---

### Edge Cases

- 无 text/plain 只有 HTML：转为纯文本后再截断。
- charset 未知：best-guess 并记录 `decoded_with`，不得用 utf-8/replace 吞掉 GB 邮件。
- 同一 UID 出现在 INBOX 与 Sent：正文映射按 folder#uid，互不覆盖。
- 一次增量超过采样上限：采最新 N 封，不是最旧 N 封。
- 真实 IMAP / 真实 LLM 在单元测试中不可用：用构造邮件与 mock。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST decode IMAP message bodies to UTF-8 plain text (multipart, CTE, charset including utf-8 / gb18030 / gb2312 / big5 / latin-1) before analysis or extract output.
- **FR-002**: System MUST strip attachment and inline-image payloads from `body_text` while retaining attachment metadata.
- **FR-003**: Analysis prompt MUST group envelopes by thread, mark the latest message, and size body previews on decoded text (latest message preview longer than siblings).
- **FR-004**: Pending / waiting_on_me MUST be decided from the latest message in the thread; approval-style replies MUST clear waiting_on_me.
- **FR-005**: Queue tags from analysis artifacts MUST join pulse threads via one shared thread-key normalizer; misses MUST be visible in diagnostics and status.
- **FR-006**: `latest_mail` / `todo` / `weekly` MUST expose `staleness` and auto-sync when stale; failed auto-sync MUST NOT return a stale snapshot as success.
- **FR-007**: Sync MUST report analysis failure as degraded (not silent full success) and expose fetch/analysis/pulse consistency timestamps.
- **FR-008**: Extract MUST return decoded `body_text` (bounded) plus attachment metadata, and accept optional local-hour filters.
- **FR-009**: Body sample keys MUST be folder-qualified; sampling MUST prefer newest envelopes.
- **FR-010**: Pulse scoring MUST age stale sla_risk items and boost explicit action verbs from a tracked config file.
- **FR-011**: Thread inspect MUST include latest decoded body or an explicit unavailable flag.
- **FR-012**: Status MUST expose pipeline stage timestamps and missed scheduled runs.
- **FR-013**: Existing MCP tool names and existing JSON field names MUST remain; new fields are additive only.
- **FR-014**: Real mailbox MUST remain read-only.

### Key Entities

- **DecodedBody**: 解码后的纯文本 + charset 记录 + 附件元数据列表。
- **ThreadKey**: 归一化后的线程键（去回复前缀、大小写、尾部日期）。
- **Staleness**: `{stale, age_hours, threshold_hours}` 相对 pulse `generated_at`。
- **PipelineHealth**: fetch / analysis / pulse 最近成功时间与 missed_runs。
- **QueueJoinMiss**: 无法投影到 pulse 线程的分析 thread_key。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 对构造的 GB2312 multipart 夹具，解码结果人工可读且 grep 不到 MIME `Content-Type` 残留。
- **SC-002**: 回放 2026-09-03 事故状态：辽宁白名单不在 pending；验收登记进入 pending 或 daily_urgent。
- **SC-003**: 同一回放中分析产出的 pending 条目 100% join 到 pulse，或进入 resolved；`queue_join_misses` 为空。
- **SC-004**: pulse 回拨 2 天后调用 latest_mail 会自动同步或明确失败，不出现「ok 且 generated_at 仍为两天前」。
- **SC-005**: 每个 P0/P1 需求至少 1 个不连真实 IMAP/LLM 的回归测试；`tests/mcp-smoke.mjs` 通过。

## Assumptions

- 实现在后续 `/speckit-implement`；本轮只冻结契约。
- 回放使用 `~/.twinbox` 的**副本**，不修改真实 IMAP。
- 本地 MCP 返回解码正文符合 constitution II（平台 ingest 仍禁全文；001 未实现）。
- `new_envelope_count` 语义保持「本次新入库信封数」；文档化即可，不改计数公式除非测出实现 bug。
- 历史输入 [`twinbox-evolution-prompt.md`](../../twinbox-evolution-prompt.md) 不是权威来源；冲突以本 spec 为准。
