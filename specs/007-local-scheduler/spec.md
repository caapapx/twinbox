# Feature Specification: Local Scheduler

**Feature Directory**: `007-local-scheduler`

**Created**: 2026-09-08

**Status**: Draft

**Input**: 用本机 crontab 驱动 `schedule run-due`，替换死掉的 `twinbox-orchestrate`；不加 in-process daemon。决策见 [ADR-003](../../docs/decisions/ADR-003-retrieval-spine-and-external-services.md)。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 到期任务可被 cron 跑起来 (Priority: P1)

操作者在 crontab 挂 `python3 -m twinbox_core.cli schedule run-due --json`。进程用文件锁互斥；到期则跑 `daytime-sync` 或 `nightly-full`；未到期立即退出 0。

**Why this priority**: as-built `config/schedules.yaml` 无执行器，pulse 会陈旧。

**Independent Test**: 把 due 时间拨到过去，run-due 调用 sync；拨到未来则跳过。并发第二进程拿不到锁。

**Acceptance Scenarios**:

1. **Given** 12:00 daytime 已到期且无其他 run-due，**When** 执行 `schedule run-due`，**Then** 触发对应 job 并更新 last-run。
2. **Given** 另一 run-due 持锁，**When** 第二进程启动，**Then** 立即退出且不启动第二轮 IMAP。
3. **Given** 无到期项，**When** run-due，**Then** `ok: true`、`ran: []`。

### User Story 2 - status 能看到管道与漏跑 (Priority: P1)

`twinbox_status` 暴露 `pipeline`（fetch/analysis/pulse 最近成功）与 `missed_runs`。连续错过至少两次计划运行时 warnings 非空。

**Why this priority**: `002` FR-012 需要执行器才能算漏跑。

**Independent Test**: 伪造 last-run 早于两次计划点，status.missed_runs 非空。

**Acceptance Scenarios**:

1. **Given** 连续错过至少两次计划运行，**When** status，**Then** warnings 列出 missed_runs。
2. **Given** 刚成功 run-due，**When** status，**Then** pipeline 时间更新且 missed_runs 不含刚完成的 job。

### User Story 3 - 替换死调度名 (Priority: P2)

`config/schedules.yaml` 不再引用 `twinbox-orchestrate`。文档写明 site crontab 示例（12:00 / 02:00）。

**Independent Test**: grep 追踪配置无 `twinbox-orchestrate`。

## Edge Cases

- sync 失败：run-due `ok: false` 或 degraded，不得把 last-run 标成功。
- 时钟回拨：last-run 在未来则跳过并 warning。
- 无 schedules.yaml：使用内置 12:00 daytime / 02:00 nightly。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide `schedule run-due` that runs due jobs under an exclusive file lock (`fcntl`).
- **FR-002**: System MUST persist last successful run per job without writing the mailbox.
- **FR-003**: `twinbox_status` MUST expose `pipeline` and `missed_runs`.
- **FR-004**: Tracked schedule config MUST call the current CLI, not `twinbox-orchestrate`.
- **FR-005**: Cron is external (site crontab). Twinbox MUST NOT start an in-process timer or Unix-socket daemon.
- **FR-006**: Existing MCP tool names remain; schedule may be CLI-only or additive status fields.

### Key Entities

- **ScheduleJob**: id、cron 或 clock、job 名（daytime-sync / nightly-full）。
- **RunLock**: state-root 文件锁。
- **PipelineHealth**: fetch / analysis / pulse 时间与 missed_runs。

## Success Criteria *(mandatory)*

- **SC-001**: 并发两个 run-due，IMAP sync 只出现一次。
- **SC-002**: 连续错过至少两次计划运行时 missed_runs 非空（测试可拨时间）。
- **SC-003**: 配置与文档无 `twinbox-orchestrate`。

## Assumptions

- on site Twinbox checkout 路径在 Sprint 0 探查后写入本目录 plan。
- 不实现 OpenClaw deploy/bridge。

## Out of Scope

- systemd 用户单元（site has no systemd 用户会话假设）。
- 邮件写回与 SMTP。
