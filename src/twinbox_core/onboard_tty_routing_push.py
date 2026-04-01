"""TTY steps for routing_rules + push_subscription during openclaw onboard (Phase 1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from twinbox_core.llm import LLMError, call_llm, clean_json_text
from twinbox_core.onboarding import complete_stage, load_state, save_state
from twinbox_core.onboarding_push import confirm_push_subscription
from twinbox_core.routing_rules import add_or_merge_rule


class _PastePrompter(Protocol):
    def paste_block(
        self,
        title: str,
        *,
        end_marker: str = ".",
        hint: str | None = None,
    ) -> str: ...

    def select(
        self,
        prompt: str,
        options: list[dict[str, str]],
        *,
        default: str | None = None,
        layout: str = "vertical",
    ) -> str: ...

    def note(self, title: str, body: str, *, complete: bool | None = None) -> None: ...


def _rules_path(state_root: Path) -> Path:
    return state_root / "config" / "routing-rules.yaml"


def _draft_rule_from_natural_language(
    description: str,
    *,
    env_file: Path,
    max_chars: int = 4000,
) -> dict[str, Any]:
    text = (description or "").strip()
    if not text:
        raise ValueError("empty description")
    clipped = text[:max_chars]
    system = (
        "You output ONLY one JSON object (no markdown fences) for Twinbox routing rules. "
        "Schema: keys id (string, snake_case), name (short Chinese or English), active (true), "
        "description (string), conditions: { match_all: [ { field, operator, value } ] }, "
        "actions: { set_state (string|null), set_waiting_on (null), add_tags (string[]), skip_phase4 (bool) }. "
        "field is one of: recipient_role, semantic_intent, latest_subject, domain. "
        "recipient_role operators: in, not_in, equals; value string or array of strings. "
        "semantic_intent: operator is_true or is_false; value is a Chinese/English intent sentence. "
        "Prefer monitor_only + skip_phase4 true for noise/newsletter rules. "
        "Do not invent unrelated rules."
    )
    user = f"User wants this email routing behavior:\n\n{clipped}\n\nReturn the rule JSON object only."
    raw = call_llm(user, max_tokens=1024, system_prompt=system, env_file=str(env_file))
    cleaned = clean_json_text(raw)
    rule = json.loads(cleaned)
    if not isinstance(rule, dict):
        raise ValueError("rule is not an object")
    return rule


def run_routing_rules_tty(
    state_root: Path,
    env_file: Path,
    prompter: _PastePrompter,
    *,
    use_llm: bool,
) -> dict[str, Any]:
    """Interactive routing_rules: skip, paste JSON, or natural language (+ optional LLM)."""
    st = load_state(state_root)
    if st.current_stage != "routing_rules":
        return {"skipped": True, "reason": f"current_stage={st.current_stage}"}

    prompter.note(
        "Routing rules",
        (
            "Semantic routing (optional). You can skip, paste a full rule JSON (see config/routing-rules.yaml), "
            "or describe the filter in plain language."
        ),
        complete=False,
    )
    choice = prompter.select(
        "How do you want to set routing rules?",
        options=[
            {"value": "skip", "label": "Skip", "description": "No rule; continue onboarding."},
            {"value": "json", "label": "Paste JSON", "description": "One rule object; end with ."},
            {"value": "natural", "label": "Describe in words", "description": "LLM drafts JSON if enabled."},
        ],
        default="skip",
        layout="vertical",
    )

    if choice == "skip":
        complete_stage(st, "routing_rules")
        save_state(state_root, st)
        return {"skipped": True, "advanced": True}

    rules_file = _rules_path(state_root)

    if choice == "json":
        raw = prompter.paste_block("Rule JSON (one object)", hint="End with a line containing only .")
        raw = raw.strip()
        if not raw:
            prompter.note("Routing rules", "Empty paste — skipping rule add.", complete=None)
            complete_stage(st, "routing_rules")
            save_state(state_root, st)
            return {"skipped": True, "advanced": True}
        try:
            rule = json.loads(raw)
        except json.JSONDecodeError as exc:
            prompter.note("Routing rules", f"Invalid JSON: {exc}. Skipping rule; advance anyway.", complete=None)
            complete_stage(st, "routing_rules")
            save_state(state_root, st)
            return {"ok": False, "error": str(exc), "advanced": True}
        if not isinstance(rule, dict):
            complete_stage(st, "routing_rules")
            save_state(state_root, st)
            return {"ok": False, "error": "not an object", "advanced": True}
        add_or_merge_rule(rules_file, rule)
        complete_stage(st, "routing_rules")
        save_state(state_root, st)
        return {"ok": True, "rule_id": rule.get("id"), "advanced": True}

    # natural language
    desc = prompter.paste_block("Describe the filter (plain language)", hint="End with .")
    if not desc.strip():
        complete_stage(st, "routing_rules")
        save_state(state_root, st)
        return {"skipped": True, "advanced": True}
    if not use_llm:
        prompter.note(
            "Routing rules",
            "LLM polish was off — cannot draft rule from text. Skipping file write; advancing stage.",
            complete=None,
        )
        complete_stage(st, "routing_rules")
        save_state(state_root, st)
        return {"skipped": True, "advanced": True}
    try:
        rule = _draft_rule_from_natural_language(desc, env_file=env_file)
    except (LLMError, json.JSONDecodeError, ValueError) as exc:
        prompter.note("Routing rules", f"Could not build rule: {exc}. Advancing without saving.", complete=None)
        complete_stage(st, "routing_rules")
        save_state(state_root, st)
        return {"ok": False, "error": str(exc), "advanced": True}
    add_or_merge_rule(rules_file, rule)
    complete_stage(st, "routing_rules")
    save_state(state_root, st)
    return {"ok": True, "rule_id": rule.get("id"), "advanced": True}


def run_push_subscription_tty(
    state_root: Path,
    prompter: _PastePrompter,
    *,
    session_target: str,
    openclaw_bin: str,
    twinbox_bin: str | None,
) -> dict[str, Any]:
    st = load_state(state_root)
    if st.current_stage != "push_subscription":
        return {"skipped": True, "reason": f"current_stage={st.current_stage}"}

    prompter.note(
        "Push subscription",
        (
            "Subscribe this OpenClaw session to daily/weekly digests. Requires host bridge timer enabled. "
            f"Session target: {session_target}"
        ),
        complete=False,
    )
    choice = prompter.select(
        "Enable push digests for this session?",
        options=[
            {"value": "both_on", "label": "Daily + weekly (default)", "description": "Recommended."},
            {"value": "daily_only", "label": "Daily only", "description": ""},
            {"value": "weekly_only", "label": "Weekly only", "description": ""},
            {"value": "skip", "label": "Skip for now", "description": "Finish onboarding without push subscribe."},
        ],
        default="both_on",
        layout="vertical",
    )

    if choice == "skip":
        complete_stage(st, "push_subscription")
        save_state(state_root, st)
        return {"skipped": True, "advanced": True, "subscription": None}

    daily = choice in ("both_on", "daily_only")
    weekly = choice in ("both_on", "weekly_only")
    result = confirm_push_subscription(
        state_root,
        session_target,
        daily=daily,
        weekly=weekly,
        openclaw_bin=openclaw_bin,
        twinbox_bin=twinbox_bin,
    )
    if not result.get("ok"):
        prompter.note(
            "Push subscription",
            f"Subscribe failed: {result.get('error', 'unknown')}. "
            "You can run `twinbox host bridge install` later and confirm push in OpenClaw.",
            complete=None,
        )
        return {**result, "advanced": False}

    st = load_state(state_root)
    if st.current_stage == "push_subscription":
        complete_stage(st, "push_subscription")
        save_state(state_root, st)
    return {**result, "advanced": True}


_DEFAULT_SESSION = "agent:twinbox:main"


def default_push_session_target() -> str:
    import os

    for key in ("TWINBOX_PUSH_SESSION_TARGET", "OPENCLAW_SESSION_ID", "OPENCLAW_SESSION"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    return _DEFAULT_SESSION


def advance_past_material_if_stuck(
    state_root: Path,
    prompter: _PastePrompter,
) -> None:
    """If still on material_import after TTY context, offer skip to reach routing_rules in same wizard."""
    st = load_state(state_root)
    if st.current_stage != "material_import":
        return
    skip = prompter.select(
        "Materials: you did not save a reference paste in this run. Skip materials for now?",
        options=[
            {"value": "yes", "label": "Skip materials", "description": "Continue to routing rules in TTY."},
            {"value": "no", "label": "Stop here", "description": "Finish materials later in OpenClaw."},
        ],
        default="no",
        layout="horizontal",
    )
    if skip == "yes":
        complete_stage(st, "material_import")
        save_state(state_root, st)


def ensure_at_routing_rules_stage(
    state_root: Path,
    prompter: _PastePrompter,
) -> bool:
    """
    If onboarding is still on profile_setup or material_import, offer one-shot skip to reach routing_rules
    for TTY rule + push. Returns False if user declines (continue in OpenClaw for those stages).
    """
    st = load_state(state_root)
    if st.current_stage == "routing_rules":
        return True
    if st.current_stage in ("push_subscription", "completed"):
        return True
    if st.current_stage not in ("profile_setup", "material_import", "llm_setup"):
        return True

    jump = prompter.select(
        "Configure routing + push in this terminal now?",
        options=[
            {
                "value": "yes",
                "label": "Yes — skip unfinished profile/material here",
                "description": "OpenClaw can still edit human-context later.",
            },
            {
                "value": "no",
                "label": "No — finish profile/material in OpenClaw first",
                "description": "TTY routing/push steps will be skipped this run.",
            },
        ],
        default="yes",
        layout="horizontal",
    )
    if jump != "yes":
        return False

    st = load_state(state_root)
    order = [
        "not_started",
        "mailbox_login",
        "llm_setup",
        "profile_setup",
        "material_import",
        "routing_rules",
        "push_subscription",
        "completed",
    ]
    target_idx = order.index("routing_rules")
    while order.index(st.current_stage) < target_idx:
        complete_stage(st, st.current_stage)  # type: ignore[arg-type]
        save_state(state_root, st)
        st = load_state(state_root)
    return True
