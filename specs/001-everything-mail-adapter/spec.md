# Feature Specification: Everything Mail Adapter

**Feature Branch**: `001-everything-mail-adapter`

**Created**: 2026-08-26

**Status**: Partial — multi-account vault + accounts/ingest/events tools landed; full ingest axes / pack event types still open

> 代码事实：当前 `master` 已落地多账号 vault、`twinbox_accounts` / `twinbox_ingest` / `twinbox_events` 与最小可观测性；六轴归类与完整事件类型仍未收敛。不要把它描述为已实现能力。权威顺序：代码 > constitution > 本契约。As-built 见 [`specs/000-as-built-mcp-baseline`](../000-as-built-mcp-baseline/spec.md)。本契约是**数据平面**（账号接入、引用式 ingest、事件记录输出），不承担周报运营 UI（`004`）、注意力 onboarding（`005`）或邮箱写操作/流程执行（`006`）。事件类型与归类轴的领域含义由 [`003`](../003-semantic-context-event-intelligence/spec.md) 语义包声明；此处只约束 envelope 与隔离。

**Input**: User description: "twinbox 作为 Agent OS Everything 过程数据层的邮件 adapter：公共邮箱接入、多用户集中管理与凭据加密、邮件数据以 ingest.attributes（版本化 opaque 归类轴）形式输出给平台、OS 侧只收引用不收全文、按可配置事件类型抽取（样例：周报/风险/计划变更）。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 公共邮箱只读接入 (Priority: P1)

部门管理员把一个公共邮箱（如团队 support / project 邮箱）配置进 twinbox，twinbox 以只读 IMAP 方式同步该邮箱，产出与现有个人邮箱一致的线程分析与队列视图，且全程不对服务器做任何写操作。

**Why this priority**: 没有公共邮箱接入，adapter 就无数据可输出；这是整个 feature 的数据源前提，且可独立于平台对接交付价值（管理员本地即可查看公共邮箱的紧急/待回复）。

**Independent Test**: 配置一个公共邮箱账号后运行 `python3 -m twinbox_core.cli sync --json`，确认线程进入本地队列、工具输出正常，且通过 IMAP 日志/测试账号验证没有任何 send/move/delete/archive/flag 操作。

**Acceptance Scenarios**:

1. **Given** 管理员在本地配置中登记了一个公共邮箱账号，**When** 触发同步，**Then** 该邮箱的邮件以只读方式进入 twinbox 的线程分析与队列视图。
2. **Given** 公共邮箱凭证无效或过期，**When** 触发同步，**Then** 工具返回结构化错误与恢复指引（`recovery_tool`），不暴露凭证内容。
3. **Given** 已同步的公共邮箱，**When** 任意 twinbox 工具被调用，**Then** 邮箱服务器侧状态不发生任何变化（读操作除外）。

---

### User Story 2 - Everything ingest 输出（引用 + 多轴归类） (Priority: P2)

Agent OS 平台调用 twinbox 的 ingest 工具，得到一批 ingest envelope：每条包含稳定引用（账号 + message/thread ID）、有限元数据（主题、发件人、日期、截断摘要）与版本化 `attributes` opaque 归类结果。平台侧始终收不到邮件全文。

**Why this priority**: 这是 adapter 对平台的核心价值契约；在公共邮箱接入就绪后即可独立交付与验证（可先用个人测试邮箱产出 envelope）。

**Independent Test**: 对一封已知内容的测试邮件调用 ingest 输出工具，断言返回结构包含引用与 attributes map、不含正文字段、摘要长度受控。

**Acceptance Scenarios**:

1. **Given** 已同步的邮件线程，**When** 平台调用 ingest 工具，**Then** 每条记录包含稳定引用、有限元数据和 `attributes` opaque map，且不包含邮件正文或附件内容。
2. **Given** 归类规则在 twinbox 侧调整（如新增一个意图取值或轴名），**When** 平台再次拉取，**Then** envelope 外层形状不变，轴值按新规则输出，平台无需改动写死枚举的代码。
3. **Given** 平台请求增量数据，**When** 提供 since 游标，**Then** 只返回游标之后新增或变化的记录，游标语义稳定可重放。

---

### User Story 3 - 多用户集中管理与凭据加密 (Priority: P2)

管理员在一处集中管理多个邮箱账号（个人 + 公共），所有凭据以加密形式存储在本地 vault 中；任何工具输出、日志、受追踪文件都不出现凭据明文，只暴露 `password_set: true` 一类的存在性布尔值。

**Why this priority**: 企业级多邮箱是部门部署的硬要求；凭据加密是安全底线。它与 ingest 输出相互独立（加密只影响存储层），可并行推进。

**Independent Test**: 登记两个账号后检查 vault 文件无明文、工具状态输出只含存在性布尔值，且加密 vault 在 twinbox 重启后仍可正常解密使用。

**Acceptance Scenarios**:

1. **Given** 管理员登记新账号，**When** 查看本地存储文件，**Then** 凭据字段为密文，无明文可 grep。
2. **Given** 已登记账号，**When** 调用状态/设置类工具，**Then** 输出只含凭据存在性布尔值，不回显任何凭据材料。
3. **Given** 多账号并存，**When** 同步与 ingest，**Then** 各账号数据相互隔离，输出记录可追溯到来源账号。

---

### User Story 4 - 可配置事件抽取（数据平面） (Priority: P3)

twinbox 在 ingest envelope 之上提供事件抽取：按 Semantic Pack / 配置声明的事件类型从邮件流识别结构化事件，以独立事件记录输出给平台；事件只携带引用与抽取字段，不携带全文。`weekly_report` / `risk` / `plan_change` 仅为验收样例类型，不是不可替换的核心枚举。

**Why this priority**: 事件是下游（含 `003`/`004`）的高价值输入，但依赖 ingest 先稳定，故排 P3。

**Independent Test**: 构造含样例语义的测试邮件，调用事件抽取工具，断言产出对应类型事件、字段完整、无正文；更换包内类型名后 envelope 形状仍稳定。

**Acceptance Scenarios**:

1. **Given** 一封匹配样例 `weekly_report` 规则的邮件，**When** 运行事件抽取，**Then** 产出该类型事件，含周期、作者引用与要点摘要，不含正文。
2. **Given** 一封匹配样例 `risk` 规则的邮件，**When** 运行事件抽取，**Then** 产出该类型事件，含风险描述摘要与严重度归类。
3. **Given** 同一事件被重复抽取，**When** 平台二次拉取，**Then** 事件记录按稳定 ID 去重，不产生重复。

---

### Edge Cases

- 公共邮箱邮件量远超个人邮箱时，同步与 ingest 分批处理，单次输出有明确上限与分页游标。
- LLM 不可用或超时：归类/抽取降级为规则兜底或标记 `unclassified`，不阻塞同步主流程。
- 敏感轴命中高敏邮件：摘要进一步截断或省略，引用仍然可用。
- 同一封邮件被多个账号收到（转发/抄送公共邮箱）：按账号分别引用，thread 轴可跨账号关联。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support registering shared/public mailboxes alongside personal accounts, all accessed via read-only IMAP.
- **FR-002**: System MUST produce ingest envelopes containing a stable reference (account ID + message/thread ID), bounded metadata, and a versioned `attributes` object as an opaque map/list of classification axes defined in twinbox-side config/Semantic Packs (illustrative starter axes may include person, thing, intent, urgency, sensitivity, thread — not a frozen consumer enum).
- **FR-003**: System MUST NOT include email full text or attachment content in any platform-facing output; summaries/excerpts MUST be length-bounded.
- **FR-004**: Classification axes and their value rules MUST be defined in twinbox-side configuration (e.g. `config/extract-profiles.yaml`) and changeable without platform-side code changes.
- **FR-005**: System MUST store all credentials encrypted at rest in a local vault under `~/.twinbox/`; plaintext credentials MUST NOT appear in outputs, logs, or tracked files.
- **FR-006**: System MUST support centralized multi-account management (add/list/remove accounts) with outputs exposing only presence booleans for credentials.
- **FR-007**: System MUST provide incremental ingest via a stable cursor (since-token), replayable and idempotent.
- **FR-008**: System MUST extract structured events as separate records carrying references and extracted fields only, deduplicated by stable event ID; minimum starter types for acceptance MAY include weekly_report, risk, and plan_change, and MUST remain pack-configurable.
- **FR-009**: New capabilities MUST be exposed as new `twinbox_*` MCP tools or new fields inside existing `data` payloads, preserving the envelope shape (`ok`/`data`/`error`/`recovery_tool`).
- **FR-010**: System MUST keep per-account data isolated and every output record traceable to its source account.

### Key Entities *(include if feature involves data)*

- **MailboxAccount**: 一个已登记的邮箱（个人或公共）。属性：账号 ID、类型（personal/shared）、服务器连接参数、凭据引用（指向 vault，不含值）、同步状态。
- **MailReference**: 平台可用的稳定引用。属性：账号 ID、message ID、thread ID、subject、sender、date、有界摘要。
- **IngestEnvelope**: 输出给 Agent OS 的记录单元。属性：reference（MailReference）、attributes（版本化 opaque 归类图）、extracted events 链接、cursor。
- **ClassificationAxes**: twinbox 侧配置的归类轴与取值规则集合，版本化管理；键对平台透明。
- **CredentialVault**: 本地加密凭据存储。属性：账号 ID → 密文条目；主密钥不入库、不入追踪文件。
- **EventRecord**: 结构化事件（类型由包声明；样例含 weekly_report / risk / plan_change）。属性：稳定事件 ID、类型、引用、抽取字段摘要、去重键。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 管理员 5 分钟内完成一个公共邮箱的登记与首次只读同步，无需阅读代码。
- **SC-002**: 平台对任意 ingest 响应做全文扫描（自动化检查），0 条记录包含邮件正文或附件内容。
- **SC-003**: 归类规则在 twinbox 侧新增一个意图取值后，平台侧 0 行代码改动即可继续消费。
- **SC-004**: 对 vault 存储文件与仓库追踪文件做明文口令扫描，命中数为 0。
- **SC-005**: 1000 封邮件的批量 ingest 在分页游标下可完整重放，重复率为 0。
- **SC-006**: 对含周报/风险语义的测试邮件集，事件抽取召回率 ≥ 80%（人工标注对照）。

## Assumptions

- Agent OS 侧已有 ingest 接收端，契约以 envelope 结构为准；平台不反向调用 twinbox 内部模块。
- 公共邮箱支持 IMAP 且允许只读访问（应用专用密码或 OAuth 均可，v1 先支持应用专用密码）。
- 归类与抽取继续复用现有 LLM 通路（`twinbox_core/llm.py`），不引入新的模型供应商。
- v1 数据平面不包含邮箱写回；策略约束的自动转发/推进见 `006` 与 [ADR-002](../../docs/decisions/ADR-002-read-only-to-policy-governed-execution.md)，不在本契约范围。
- 多用户集中管理的「用户」指部门管理员视角的账号管理，不含面向终端用户的权限系统。
- 组织级周报缺交运营与注意力三投影分别见 `004` / `005`，不在本 adapter 内实现完整产品面。
