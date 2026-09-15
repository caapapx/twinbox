# Feature Specification: As-Built MCP Baseline

**Feature Directory**: `000-as-built-mcp-baseline`

**Created**: 2026-09-04

**Status**: Frozen baseline（retroactive as-built；**不是**历史按 SpecKit 开发的 provenance）

**Input**: 将 SpecKit 插入前已落地的 `master` 行为冻结为可引用事实基线，供后续 feature/ADR 对照，避免把 Planned 合同误写成已实现。

## Purpose

本目录记录 **as-is / as-built** 能力与已知缺口。权威顺序仍是：代码与测试 > constitution > 本 baseline > 其他 Planned 合同。

验证细节见 [verification.md](./verification.md)。

## Capability Inventory

### Implemented

| Capability | Evidence |
| --- | --- |
| 单邮箱 IMAP 只读抓取 | `twinbox_core/imap_fetch.py`（`readonly=True`） |
| 单次 LLM 分析：urgent / pending / SLA / weekly_brief | `twinbox_core/analyze.py` |
| Activity pulse + needs_attention | `twinbox_core/pulse.py` |
| 本地 queue complete/dismiss/restore | `twinbox_core/queue.py`（不写回邮箱） |
| 历史/定向 extract（含 `weekly_report` profile） | `twinbox_core/extract.py`、`config/extract-profiles.yaml` |
| 9 个 MCP 工具 | `mcp-server.mjs`、`tests/mcp-smoke.mjs` |
| CLI 入口 | `python3 -m twinbox_core.cli <cmd> --json` |
| 基础 setup / status | `twinbox_core/cli.py`、`config.py` |

### Partial

| Capability | 现状 |
| --- | --- |
| 调度汇总 | 合同在 [`specs/007-local-scheduler`](../007-local-scheduler/spec.md)；as-built 仅有 `config/schedules.yaml`，无执行器 |
| 「特别关注」 | 仅有带 queue_tags 的 `needs_attention`，无独立 watch/reference 投影 |
| Onboarding | env/配置导入，非语义包问卷 |
| 周报 | `twinbox_weekly` = 当前 sync 产物；extract profile 可搜历史周报主题；**无**组织级准时/缺交统计 |

### Absent（勿描述为已上线）

- 多账号 / 加密 vault / `twinbox_accounts`
- Agent OS ingest envelope / `twinbox_ingest`
- 结构化事件工具 / `twinbox_events`
- 组织树、邮箱组、roster
- 外部确认通道（chat webhook）
- SMTP 或邮箱转发/发送
- `specs/002-analysis-correctness` 中的 MIME 解码、staleness、queue_join_misses 等（合同 Draft，任务未勾选）

### Known Gaps（合规/文档 vs 代码）

1. **凭据**：`setup_from_env` 可将 IMAP 密码写入 `~/.twinbox/twinbox.json` 明文；Constitution V 要求加密 vault + 输出仅 `password_set`。见 verification。
2. **分类配置**：Constitution / `001` 常引用 `extract-profiles.yaml` 为归类轴源；该文件当前仅为查询预设（如 weekly_report），**不是**已实现的六轴分类配置。
3. **Envelope 形状**：constitution 描述 MCP `ok/data/error/recovery_tool`；CLI 多数直接返回带 `ok` 的字段对象。新工具应与 MCP 层约定对齐后再扩展。

## Out of Scope

- 不把本 baseline 当作实现任务清单。
- 不收录已废弃 monolith（`archive/openclaw-monolith`）能力。
- 不收录会议纪要中的产品愿景（见 `003`–`006` 与 ADR）。

## Assumptions

- SpecKit 于 2026-09-03 起插入；此前半年开发未反向生成完整 SpecKit 验收史。
- Active 实施焦点默认仍为 `specs/002-analysis-correctness`（见 `.specify/feature.json`）。
