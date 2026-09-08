"""Minimal onboarding questionnaire → user Semantic Pack."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .pack import validate_pack

QUESTIONS = [
    {"id": "approvals", "prompt": "日常需要你审批或回复的是什么？"},
    {"id": "watch", "prompt": "特别关注谁或什么主题？"},
    {"id": "extra", "prompt": "额外留意的方向？"},
    {"id": "broadcast", "prompt": "制度/通告默认进参考类吗？（跳过=是）"},
    {"id": "sensitive", "prompt": "需要单独标记的敏感话题？"},
]


def answers_to_pack(answers: dict[str, str]) -> dict[str, Any]:
    hints = []
    for key in ("approvals", "watch", "extra", "sensitive"):
        text = str(answers.get(key, "") or "").strip()
        if text:
            hints.append({"id": key, "utterances": [text], "threshold_high": 0.82, "threshold_low": 0.55})
    broadcast = str(answers.get("broadcast", "") or "").strip()
    classification = {
        "event_types": [{"id": "attention", "when": {}}],
        "defaults": {"broadcast": "reference" if broadcast.lower() in {"", "yes", "y", "是", "跳过"} else "watch"},
    }
    pack = {
        "id": "user",
        "version": "1.0.0",
        "entities": [],
        "relations": [],
        "classification": classification,
        "attention_hints": hints,
        "routing_conditions": [],
        "action_policy": [],
    }
    return validate_pack(pack)


def save_user_pack(state_root: Path, answers: dict[str, str]) -> dict[str, Any]:
    pack = answers_to_pack(answers)
    path = state_root / "packs" / "user.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"ok": True, "path": str(path), "id": pack["id"], "version": pack["version"], "fingerprint": pack["fingerprint"]}
