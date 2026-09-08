# Implementation Plan: Attention Policy and Onboarding

**Branch**: `master` (spec dir `005-attention-policy-onboarding`) | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-attention-policy-onboarding/spec.md`

## Summary

范围收敛到 US1 最小问卷（≤5 问 → pack）+ US2 三投影（`action_required` / `watch` / `reference`）。紧急度与行动性分轴。消费 `002` 正确性信号与 `003` pack，不重做 MIME。

## Technical Context

**Language/Version**: Python 3.11+；MCP 薄封装

**Primary Dependencies**: `003` pack loader；无新第三方包

**Storage**: 问卷结果写入 `~/.twinbox/packs/user.yaml`（或合并进已装载 pack 的 attention 段）

**Testing**: pytest 构造线程；无真实 IMAP

**Target Platform**: 本机 MCP

**Project Type**: library + MCP tool server

**Performance Goals**: 投影在现有 pulse 构建时间内完成

**Constraints**: 无包时偏 reference；硬规则优先于 LLM；既有 9 工具名不变，投影 additive 进 `latest_mail` / `todo`

**Scale/Scope**: 单用户问卷；不做完整产品向导 UI

## Constitution Check

- **I**: 问卷只写本地 pack。✅
- **II**: 投影项带引用与 why，默认不塞全文。✅
- **III**: 关注点进 pack。✅
- **IV**: 新工具 `twinbox_onboard` 可选；或 CLI `onboard`。既有字段 additive。✅
- **V**: 问卷不含凭据。✅

## Project Structure

```text
twinbox_core/onboard.py
twinbox_core/project.py
tests/test_onboard.py
tests/test_project.py
```

## Phase 1: Design

五问上限（plan 常量）：(1) 日常需审批什么 (2) 特别关注谁/什么 (3) 额外留意方向 (4) 制度通告是否进 reference（可跳过） (5) 敏感话题是否单独标。答案映射到 pack `attention_hints` / `classification` / 默认投影。

三投影消费：`recipient_role`、pack action_hint、`002` pending/urgent、规则 skip。每条必须有 `why` + 投影桶。archive Phase 3 生命周期不迁独立 LLM 阶段；`resolved_by_reply` 在 `002`，投影在本 feature。
