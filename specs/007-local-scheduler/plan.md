# Implementation Plan: Local Scheduler

**Branch**: `master` (spec dir `007-local-scheduler`) | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

## Summary

CLI `schedule run-due` + `fcntl` 文件锁（源自 archive `orchestration.py`）+ `status.pipeline` / `missed_runs`。由 239 cron 驱动。替换 `config/schedules.yaml` 里死掉的 `twinbox-orchestrate`。

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: stdlib `fcntl`；现有 `cmd_sync`

**Storage**: `runtime/schedule/last-run.json` + `runtime/schedule/run-due.lock`

**Testing**: pytest 用临时 state root；不连 IMAP（sync 可 mock）

**Target Platform**: Linux 239 crontab；macOS 本机可手动 run-due

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

Sprint 0：ssh 239 读 `~/.qwenpaw/config.json` 中 twinbox MCP 条目，把 checkout 路径、python、`TWINBOX_STATE_ROOT` 记入本 plan「239 接入」节。

## 239 接入

Sprint 0 探查（2026-09-08，ssh iflytek239，凭据未记录）：

- checkout（宿主）：`/iflytek/server/twinbox-server`（非 git 工作树；容器内 `/app/working/twinbox-server`）
- QwenPaw data：`/iflytek/server/qwenpaw/qwenpaw-data/`；agent profile `twinbox` workspace `/app/working/workspaces/twinbox`
- MCP 进程：`node /app/working/twinbox-server/mcp-server.mjs`（QwenPaw 容器内，宿主机另有副本）
- python：`/iflytek/server/twinbox-server/.venv/bin/python`（若存在）
- TWINBOX_STATE_ROOT：`/iflytek/server/qwenpaw/qwenpaw-data/twinbox-state`
- LLM：`http://172.30.210.251:8000/v1` 模型 `qwen3.8-27b`（勿占 8000）
- Embedding：`http://172.30.210.251:18010/v1/embeddings` 模型 `Qwen3-Embedding-8B`（4096；进程无 systemd）
- Rerank（二期，默认不配）：`http://172.30.210.251:18011/v1/rerank`
- crontab 已挂（2026-09-08）：`30 8 * * *` 与 `0 2 * * *`，`TWINBOX_STATE_ROOT=/iflytek/server/qwenpaw/qwenpaw-data/twinbox-state`，解释器 `/iflytek/server/twinbox-server/.venv/bin/python`，日志 `/var/log/twinbox-schedule.log`
- 热更：因 checkout 不是 git repo，用 rsync/scp 同步 `twinbox_core/` 与 `mcp-server.mjs` 后重启 QwenPaw 容器内 MCP 进程
