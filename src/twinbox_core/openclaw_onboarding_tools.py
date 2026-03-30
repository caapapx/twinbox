"""JSON payloads for OpenClaw native onboarding tools (shared with CLI)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from twinbox_core.human_context_store import update_human_context_store
from twinbox_core.mail_env_contract import missing_required_mail_values
from twinbox_core.env_writer import load_env_file
from twinbox_core.llm import LLMError, resolve_backend
from twinbox_core.twinbox_config import config_path_for_state_root
from twinbox_core.onboarding import (
    complete_stage,
    get_next_stage,
    get_stage_prompt,
    load_state,
    save_state,
)
from twinbox_core.onboarding_push import confirm_push_subscription


def _cc_downweight_fn(state_root: Path, value: str) -> None:
    from twinbox_core.task_cli import _set_cc_downweight_preference

    _set_cc_downweight_preference(state_root, value)


def json_onboarding_start(state_root: Path) -> dict[str, Any]:
    from twinbox_core.onboarding import get_next_stage

    state = load_state(state_root)
    if state.current_stage == "not_started":
        next_stage = get_next_stage("not_started")
        if next_stage:
            state.current_stage = next_stage
            save_state(state_root, state)
    return {
        "stage": state.current_stage,
        "prompt": get_stage_prompt(state.current_stage),
        "completed_stages": state.completed_stages,
    }


def json_onboarding_status(state_root: Path) -> dict[str, Any]:
    state = load_state(state_root)
    env_file = config_path_for_state_root(state_root)
    dotenv = load_env_file(env_file)
    missing_mail = missing_required_mail_values(dotenv)
    mailbox_ready = not missing_mail
    llm_ready = True
    try:
        resolve_backend(env_file=env_file, env={})
    except LLMError:
        llm_ready = False

    remaining = [
        s
        for s in ["mailbox_login", "llm_setup", "profile_setup", "material_import", "routing_rules", "push_subscription"]
        if s not in state.completed_stages and s != "completed"
    ]
    return {
        "current_stage": state.current_stage,
        "completed_stages": state.completed_stages,
        "remaining_stages": remaining,
        "readiness": {
            "mailbox": mailbox_ready,
            "llm": llm_ready,
        },
        "prompt": get_stage_prompt(state.current_stage) if state.current_stage != "completed" else "",
    }


def json_onboarding_advance(
    state_root: Path,
    *,
    profile_notes: str | None = None,
    calibration_notes: str | None = None,
    cc_downweight: str | None = None,
) -> dict[str, Any]:
    state = load_state(state_root)
    if state.current_stage == "not_started":
        ns = get_next_stage("not_started")
        if ns:
            state.current_stage = ns

    if state.current_stage == "completed":
        return {
            "completed_stage": None,
            "current_stage": "completed",
            "completed_stages": state.completed_stages,
            "prompt": "Onboarding already completed.",
        }

    completed_stage_name = state.current_stage
    if completed_stage_name == "profile_setup":
        if profile_notes is not None or calibration_notes is not None:
            update_human_context_store(
                state_root,
                profile_notes=profile_notes,
                calibration=calibration_notes,
            )
            state.profile_data.pop("notes", None)
            state.profile_data.pop("calibration", None)
        if cc_downweight:
            _cc_downweight_fn(state_root, cc_downweight)

    complete_stage(state, state.current_stage)
    save_state(state_root, state)
    result: dict[str, Any] = {
        "completed_stage": completed_stage_name,
        "current_stage": state.current_stage,
        "completed_stages": state.completed_stages,
        "prompt": get_stage_prompt(state.current_stage),
    }
    if state.current_stage == "push_subscription":
        result["tool_hint"] = (
            "When user confirms: call twinbox_push_confirm_onboarding(daily='on', weekly='on'). "
            "No session parameter. Do NOT look up session or stall."
        )
        result["user_question"] = (
            "Twinbox 可以为您推送：\n"
            "• 每日邮件摘要（daily digest）\n"
            "• 每周工作简报（weekly brief）\n\n"
            "默认两项均开启。确认开启，或告诉我想调整哪项？"
        )
    return result


def json_onboarding_confirm_push(
    state_root: Path,
    *,
    session_target: str,
    daily: bool = True,
    weekly: bool = True,
    openclaw_bin: str = "openclaw",
    twinbox_bin: str | None = None,
) -> dict[str, Any]:
    result = confirm_push_subscription(
        state_root,
        session_target,
        daily=daily,
        weekly=weekly,
        openclaw_bin=openclaw_bin,
        twinbox_bin=twinbox_bin,
    )
    result["prompt"] = get_stage_prompt(load_state(state_root).current_stage)
    return result
