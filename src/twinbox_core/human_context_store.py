"""Unified human-context persistence under runtime/context/human-context.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .onboarding import load_state


def human_context_path(state_root: Path) -> Path:
    return state_root / "runtime" / "context" / "human-context.yaml"


def _normalize_text(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _normalize_entries(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _normalize_store(data: object) -> dict[str, object]:
    mapping = data if isinstance(data, dict) else {}
    return {
        "profile_notes": _normalize_text(mapping.get("profile_notes")),
        "calibration": _normalize_text(mapping.get("calibration")),
        "facts": _normalize_entries(mapping.get("facts")),
        "habits": _normalize_entries(mapping.get("habits")),
    }


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _load_legacy_store(state_root: Path) -> dict[str, object]:
    runtime_context = state_root / "runtime" / "context"
    facts_payload = _load_yaml_mapping(runtime_context / "manual-facts.yaml")
    habits_payload = _load_yaml_mapping(runtime_context / "manual-habits.yaml")
    onboarding_state = load_state(state_root)
    profile_data = onboarding_state.profile_data if isinstance(onboarding_state.profile_data, dict) else {}

    calibration_path = runtime_context / "instance-calibration-notes.md"
    calibration = ""
    if calibration_path.is_file():
        calibration = calibration_path.read_text(encoding="utf-8").strip()
    if not calibration:
        calibration = _normalize_text(profile_data.get("calibration"))

    return {
        "profile_notes": _normalize_text(profile_data.get("notes")),
        "calibration": calibration,
        "facts": _normalize_entries(facts_payload.get("facts")),
        "habits": _normalize_entries(habits_payload.get("habits")),
    }


def _has_any_content(store: dict[str, object]) -> bool:
    return bool(
        store.get("profile_notes")
        or store.get("calibration")
        or store.get("facts")
        or store.get("habits")
    )


def save_human_context_store(state_root: Path, store: dict[str, object]) -> dict[str, object]:
    normalized = _normalize_store(store)
    path = human_context_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(normalized, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return normalized


def load_human_context_store(state_root: Path) -> dict[str, object]:
    path = human_context_path(state_root)
    if path.is_file():
        return _normalize_store(_load_yaml_mapping(path))

    legacy = _load_legacy_store(state_root)
    if _has_any_content(legacy):
        return save_human_context_store(state_root, legacy)
    return legacy


def update_human_context_store(
    state_root: Path,
    *,
    profile_notes: str | None = None,
    calibration: str | None = None,
) -> dict[str, object]:
    store = load_human_context_store(state_root)
    if profile_notes is not None:
        store["profile_notes"] = _normalize_text(profile_notes)
    if calibration is not None:
        store["calibration"] = _normalize_text(calibration)
    return save_human_context_store(state_root, store)


def upsert_human_context_fact(state_root: Path, fact: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    store = load_human_context_store(state_root)
    facts = _normalize_entries(store.get("facts"))
    fact_id = str(fact.get("id", "") or "")
    existing_idx = next((i for i, item in enumerate(facts) if str(item.get("id", "") or "") == fact_id), None)
    created = existing_idx is None
    if existing_idx is None:
        facts.append(dict(fact))
    else:
        facts[existing_idx] = dict(fact)
    store["facts"] = facts
    save_human_context_store(state_root, store)
    return dict(fact), created
