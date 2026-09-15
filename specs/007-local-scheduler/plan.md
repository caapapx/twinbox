# Implementation Plan: Local Scheduler

**Branch**: `master` (spec dir `007-local-scheduler`) | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

## Summary

CLI `schedule run-due` + `fcntl` 文件锁（源自 archive `orchestration.py`）+ `status.pipeline` / `missed_runs`。由宿主 crontab 驱动。替换 `config/schedules.yaml` 里死掉的 `twinbox-orchestrate`。

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: stdlib `fcntl`；现有 `cmd_sync`

**Storage**: `runtime/schedule/last-run.json` + `runtime/schedule/run-due.lock`

**Testing**: pytest 用临时 state root；不连 IMAP（sync 可 mock）

**Target Platform**: Linux crontab；macOS 本机可手动 run-due

**Project Type**: CLI

**Performance Goals**: 未到期时进程 <1s 退出

**Constraints**: 无 in-process 定时器；无 Unix-socket daemon；无 systemd 依赖

**Scale/Scope**: 两个 job（daytime-sync / nightly-full）

## Constitution Check

- **I**: 只触发既有只读 sync。✅
- **IV**: 不改九工具名；status additive。✅
- **ADR-003**: 调度委托 cron。✅

## Project Structure

```text
twinbox_core/schedule.py
twinbox_core/cli.py          # schedule run-due
config/schedules.yaml
tests/test_schedule.py
```

## Phase 0: Research

archive `orchestration.py` 的锁语义可迁；Go CLI / Himalaya / OpenClaw deploy 不迁。

Sprint 0：在部署主机读 MCP 宿主配置中的 twinbox 条目，把 checkout 路径、python、`TWINBOX_STATE_ROOT` 记入本 plan「部署接入」节（路径与 URL 不进公开仓）。

## 部署接入

现场 checkout、state root、LLM/embedding URL 只写在部署主机配置与 `~/.twinbox/`，不进 git。crontab 示例：

```cron
0 12 * * *  TWINBOX_STATE_ROOT=/path/to/state python3 -m twinbox_core.cli schedule run-due --json
0 2 * * *   TWINBOX_STATE_ROOT=/path/to/state python3 -m twinbox_core.cli schedule run-due --json
```

热更：同步 `twinbox_core/` 与 `mcp-server.mjs` 后重启 MCP 宿主进程。pytest 全绿不等于运行态已更新。
