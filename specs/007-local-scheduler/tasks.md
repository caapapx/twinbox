---
description: "Task list for local scheduler"
---

# Tasks: Local Scheduler

**Input**: `/specs/007-local-scheduler/`

## Phase 1: Setup

- [x] T001 重写 `config/schedules.yaml`：job 指向 `python3 -m twinbox_core.cli`；删除 `twinbox-orchestrate`
- [x] T002 Sprint 0 探查后回填 `plan.md`「239 接入」

## Phase 2: User Story 1 - run-due (P1)

- [x] T003 [US1] `twinbox_core/schedule.py`：解析到期、`fcntl` 锁、调用 sync job、写 last-run
- [x] T004 [US1] CLI `schedule run-due --json`
- [x] T005 [P] [US1] `tests/test_schedule.py`：到期跑；未到期空 ran；锁互斥；失败不写成功 last-run

## Phase 3: User Story 2 - status (P1)

- [x] T006 [US2] `cmd_status` 增加 `pipeline` 与 `missed_runs`（`twinbox_core/cli.py`）
- [x] T007 [US2] 连续两次漏跑 → warnings 非空（`tests/test_schedule.py`）

## Phase 4: User Story 3 - 文档 (P2)

- [x] T008 [US3] README / skill 增加 crontab 示例；grep 无 `twinbox-orchestrate`

## Phase 5: Polish

- [x] T010 239 crontab 已挂 08:30 / 02:00（2026-09-08）；连续 3 天观察 `stale=0` 仍为人工验收

## Dependencies

- T003 依赖现有 `cmd_sync`
- T006 可与 `002` T024 合并实现
