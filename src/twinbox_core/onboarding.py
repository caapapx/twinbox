#!/usr/bin/env python3
"""
Conversational onboarding flow with progress persistence.

Stages:
1. mailbox_login: Email detection + preflight
2. profile_setup: Job role, habits, preferences
3. material_import: Upload context materials
4. routing_rules: Email filtering rules
5. push_subscription: Notification preferences
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

OnboardingStage = Literal[
    "not_started",
    "mailbox_login",
    "llm_setup",
    "profile_setup",
    "material_import",
    "routing_rules",
    "push_subscription",
    "completed",
]


@dataclass
class OnboardingState:
    """Persistent onboarding progress."""

    current_stage: OnboardingStage = "not_started"
    completed_stages: list[str] = field(default_factory=list)
    mailbox_config: dict[str, Any] = field(default_factory=dict)
    profile_data: dict[str, Any] = field(default_factory=dict)
    materials: list[str] = field(default_factory=list)
    routing_rules: list[str] = field(default_factory=list)
    push_enabled: bool = False
    started_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "current_stage": self.current_stage,
            "completed_stages": self.completed_stages,
            "mailbox_config": self.mailbox_config,
            "profile_data": self.profile_data,
            "materials": self.materials,
            "routing_rules": self.routing_rules,
            "push_enabled": self.push_enabled,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> OnboardingState:
        return cls(
            current_stage=data.get("current_stage", "not_started"),
            completed_stages=data.get("completed_stages", []),
            mailbox_config=data.get("mailbox_config", {}),
            profile_data=data.get("profile_data", {}),
            materials=data.get("materials", []),
            routing_rules=data.get("routing_rules", []),
            push_enabled=data.get("push_enabled", False),
            started_at=data.get("started_at"),
            updated_at=data.get("updated_at"),
        )


def get_state_path(state_root: Path) -> Path:
    """Get onboarding state file path."""
    return state_root / "runtime" / "onboarding-state.json"


def load_state(state_root: Path) -> OnboardingState:
    """Load onboarding state from disk."""
    path = get_state_path(state_root)
    if not path.exists():
        return OnboardingState()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return OnboardingState.from_dict(data)
    except Exception:
        return OnboardingState()


def save_state(state_root: Path, state: OnboardingState) -> None:
    """Save onboarding state to disk."""
    path = get_state_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    state.updated_at = datetime.now().isoformat()
    if state.started_at is None:
        state.started_at = state.updated_at
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)


STAGE_ORDER: list[OnboardingStage] = [
    "not_started",
    "mailbox_login",
    "llm_setup",
    "profile_setup",
    "material_import",
    "routing_rules",
    "push_subscription",
    "completed",
]

STAGE_PROMPTS = {
    "mailbox_login": (
        "Phase 2 of 2 · 邮箱登录配置\n"
        "继续完成 Twinbox onboarding。请提供邮箱地址和 IMAP 密码（通过环境变量注入，不会出现在命令行参数中）。\n\n"
        "推荐方式（由 agent 调用 `twinbox_mailbox_setup` 插件工具，或在宿主机执行）：\n"
        "  TWINBOX_SETUP_IMAP_PASS=<app_password> twinbox mailbox setup --email you@example.com --json\n\n"
        "也可先只探测服务器配置：\n"
        "  twinbox mailbox detect you@example.com --json"
    ),
    "llm_setup": (
        "Phase 2 of 2 · LLM API 配置\n"
        "继续完成 Twinbox onboarding。Phase 1-4 流水线需要 LLM 后端（OpenAI 兼容 或 Anthropic）。\n\n"
        "推荐方式（由 agent 调用 `twinbox_config_set_llm` 插件工具，或在宿主机执行）：\n"
        "  TWINBOX_SETUP_API_KEY=<your_key> twinbox config set-llm --provider openai --model MODEL --api-url URL --json\n"
        "  TWINBOX_SETUP_API_KEY=<your_key> twinbox config set-llm --provider anthropic --model MODEL --api-url URL --json\n\n"
        "配置写入 state root/twinbox.json，不会泄露到命令行参数。Twinbox 不再内置默认模型或默认 API URL。"
    ),
    "profile_setup": (
        "Phase 2 of 2 · 个人画像设置\n"
        "继续完成 Twinbox onboarding。请告诉我您的职位、工作习惯和偏好，帮助我更好地理解邮件优先级。\n"
        "也请补充三点：这周主要关注谁/什么、哪些邮件可忽略、以及本周最重要的事项。\n"
        "如果您的工作很多通过 CC 跟进（例如 PM / 总监 / 运营），也请明确说明；agent 会据此建议是否关闭 CC 降权。"
    ),
    "material_import": (
        "Phase 2 of 2 · 上下文材料导入\n"
        "继续完成 Twinbox onboarding。推荐在 `twinbox onboard openclaw`（Phase 1）里用 TTY 粘贴大块参考文本（不回显全文），"
        "或执行 `twinbox context import-material --stdin --label STEM --intent reference` 从管道/粘贴写入材料。\n"
        "若仍在对话中补充：用户可粘贴 Markdown / 纯文本（含从 Excel 复制的表格文本）；无需在本机解析二进制表格。\n"
        "周报模板：先展示 `config/weekly-template.md`，再按需生成 Markdown 并用 "
        "`twinbox context import-material FILE --intent template_hint`（或 `--stdin`）导入。"
    ),
    "routing_rules": (
        "Phase 2 of 2 · 邮件过滤规则\n"
        "若已在 `twinbox onboard openclaw` TTY 中配置并推进，本阶段可能已完成。\n"
        "否则：询问是否需要语义路由规则；用户给出规则后调用 twinbox_onboarding_finish_routing_rules(rule_json=...)；"
        "跳过时 twinbox_onboarding_finish_routing_rules(skip_rules=true)。"
    ),
    "push_subscription": (
        "Phase 2 of 2 · 推送通知设置\n"
        "若已在 `twinbox onboard openclaw` TTY 中完成推送订阅，本阶段可能已完成。\n"
        "否则：确认 daily / weekly；用户确认后 **同轮** 调用 twinbox_push_confirm_onboarding(daily='on', weekly='on')，"
        "无需 session。须调用工具并输出摘要。"
    ),
}


def get_next_stage(current: OnboardingStage) -> OnboardingStage | None:
    """Get next stage in onboarding flow."""
    try:
        idx = STAGE_ORDER.index(current)
        if idx + 1 < len(STAGE_ORDER):
            return STAGE_ORDER[idx + 1]
    except ValueError:
        pass
    return None


def complete_stage(state: OnboardingState, stage: OnboardingStage) -> None:
    """Mark a stage as completed and advance to next."""
    if stage not in state.completed_stages:
        state.completed_stages.append(stage)
    next_stage = get_next_stage(stage)
    if next_stage:
        state.current_stage = next_stage


def get_stage_prompt(stage: OnboardingStage) -> str:
    """Get guidance prompt for a stage."""
    return STAGE_PROMPTS.get(stage, f"Stage: {stage}")
