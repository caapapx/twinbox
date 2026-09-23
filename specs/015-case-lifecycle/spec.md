# Feature Specification: Append-only Case Lifecycle Ledger

**Feature Directory**: `015-case-lifecycle`

**Created**: 2026-09-23

**Status**: Draft / Planned

**Input**: 既有分析行与语义包；把「某个 case 现在处于什么阶段」作为一条可审计、可回溯、可回退的事实，而不是改写历史。

## What

维护一个**追加式案例生命周期账本**（`runtime/context/case-ledger.jsonl`）。每一条记录描述一个 case 在某个 `attribute` 上的一个取值及其生效时间；账本只追加、永不改写或删除旧行。读取方按「同一 `case_ref`+`attribute` 下取 `valid_from` 最新的一行」得到当前视图。

在没有任何语义包声明生命周期时，账本从**既有分析行**推导四种状态：`open`、`waiting_on_me`、`waiting_on_others`、`closed`。推导不新增 LLM 调用、不修改分析 system prompt。

## Why

- 案例生命周期是**会演进的事实**：一封邮件可能回复、被审批、被搁置。需要把「阶段变化」留下痕迹，能回答「它现在处于什么状态、以前是什么、为什么变」。
- 经典错误是**把新状态直接覆盖旧状态**，丢失历史、无法回退。追加式账本 + 当前视图天然保留全史。
- 阶段名属于**业务语义**，不属于引擎本体；引擎只提供追加、当前视图、合法值约束与冲突标注，阶段名只来自语义包或分析行。

## User Scenarios & Testing

### User Story 1 - 追加式账本能回溯 (Priority: P1)

案例从 `open` 变到 `waiting_on_me` 再变到 `closed`。无论后来如何，之前的 `open` 与 `waiting_on_me` 两行仍在磁盘上，可被读取。

**Independent Test**: 追加三次后，jsonl 文件仍是 3 行；当前视图返回 `closed`；历史行可读。

### User Story 2 - 当前视图按有效时间取胜 (Priority: P1)

同一 `case_ref`+`attribute` 出现多行时，当前视图返回 `valid_from` 最新的一行；**后追加但 `valid_from` 更旧的行（backfill）不得成为当前值**。

**Independent Test**: 先写较新 `valid_from` 的行，再追加更旧 `valid_from` 的行；当前视图仍是最新值。

### User Story 3 - 超写只影响同一 case 的同一属性 (Priority: P1)

对同一 case 的 `attribute=A` 追加新值不影响该 case 的 `attribute=B`。

**Independent Test**: 对 `A` 追加以覆盖新值，`B` 的当前值不变。

### User Story 4 - closed 脱离需要关注但仍可查询 (Priority: P1)

一旦 case 当前值为 `closed`，它从 pulse 的 `needs_attention` 中消失，但 `thread_index` / 当前视图仍可见。

**Independent Test**: 构造 `closed` 后，`needs_attention` 不含该线程，`thread_index` 与当前视图仍含。

### User Story 5 - 非法取值 / 非法迁移标为待确认 (Priority: P1)

取值不在合法状态集合内（无包生命周期时仅四种状态）、或从 `closed` 迁移到非重新打开值，均记为 `status=needs_confirmation`，且**不成为当前值**。

**Independent Test**: 追加非法值或 `closed` 后追加非 `open` 值；该行 `status=needs_confirmation`，当前视图保持不变。

## Edge Cases

- 无语义包：只允许四种默认状态；任何其它取值 → `needs_confirmation`。
- backfill：追加行 `valid_from` 早于当前值 → 记录保留但不成为当前值。
- 非法迁移：`closed` 后再来一个非重新打开值 → 记录保留但 `needs_confirmation`，当前值仍为 `closed`。
- 重复分析：同一来源、同一状态不重复追加（避免无谓增长）；一旦状态变化才追加新行。
- 文件缺失：账本路径不存在时，当前视图为空；脉冲侧对 `closed` 的剔除为 no-op。
- 分析行可选字段：若分析行携带 `stage_proposals` / `followup` 则一并存储；**不要求**其存在。
- 账本损坏：读取异常按稳定错误抛出，不静默改写。

## Requirements

### Functional Requirements

- **FR-001**: System MUST persist every case-lifecycle observation as one append-only JSON line; MUST never rewrite or delete an earlier line.
- **FR-002**: System MUST expose a current view that, per `case_ref`+`attribute`, returns the line with the latest `valid_from`; a later append with an older `valid_from` MUST NOT become current.
- **FR-003**: System MUST record `case_ref`, `attribute`, `value`, `valid_from`, `recorded_at`, `evidence_ref`, `source`, `status` on every line.
- **FR-004**: Without a declared pack lifecycle, the engine MUST derive exactly the four states `open`, `waiting_on_me`, `waiting_on_others`, `closed` from existing analysis rows only, using no additional LLM call and no system-prompt edit.
- **FR-005**: `waiting_on_me` derives from pending rows; `closed` derives from `resolved_by_reply`; otherwise `open` (or `waiting_on_others` when the wait is on a third party).
- **FR-006**: When a label row carries `stage_proposals` or `followup`, the ledger MUST store them; their absence MUST NOT be an error.
- **FR-007**: Illegal transitions (`closed` then a non-reopen value, or a value outside the declared state set) MUST be stored with `status=needs_confirmation` and MUST NOT become current.
- **FR-008**: A case whose current state is `closed` MUST drop out of pulse `needs_attention` while remaining visible in `thread_index` and from a current-view reader.
- **FR-009**: A later envelope that pulse already treats as a valid reopen (per existing `_is_valid_reopen` semantics) MUST append `open` again.
- **FR-010**: The `classification_store` lifecycle projection MUST carry the ledger's current state per `case_ref`, derived from the ledger only (atomic replace, never rewrite/delete a ledger line), so a `closed` case stays `closed` through re-publishing.
- **FR-011**: A nightly full-window rewrite MUST NOT clear a `closed` case unless the newest envelope is a valid reopen per existing `_is_valid_reopen` semantics; such a case MUST NOT be appended an `open` that becomes current, nor re-enter `needs_attention`.

### Key Entities

- **CaseLedgerRecord**: 一行追加记录，含上述 8 个字段及可选 `stage_proposals` / `followup`。
- **CurrentView**: 按 `(case_ref, attribute)` 聚合、取最新 `valid_from` 的映射。
- **CaseState**: 取值为状态名；无包时为四种默认状态。

## Success Criteria

- **SC-001**: 账本文件严格追加，任何操作不缩短或改写既有行。
- **SC-002**: 同一 `case_ref`+`attribute` 的当前视图在 backfill 与非法迁移后仍正确。
- **SC-003**: `closed` 状态下，脉冲 `needs_attention` 不含该 case，`thread_index` 与当前视图仍含。
- **SC-004**: `twinbox_core/` 源码不含任何夹具中的示例阶段名。
- **SC-005**: `classification_store` 生命周期投影携带账本当前 `closed`，重新发布后仍为 `closed`。
- **SC-006**: 夜间整窗重写后，一个一次 `closed` 的 case 仍为 `closed`，除非最新邮件满足既有 `_is_valid_reopen`。

## Out of Scope

- 修改 `mcp-server.mjs` 工具名、R1 reopen 判定、R2 extract 来源、R3 评分默认值。
- 新增分析 LLM 调用或改动 analysis system prompt。
- 阶段名的具体业务词汇（仅存在于语义包或夹具）。
