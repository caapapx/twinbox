"""Semantic Pack load / validate / fingerprint."""

from __future__ import annotations

import copy
import math
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

FORBIDDEN_KEYS = {"script", "python", "exec", "code", "hooks", "plugin", "include"}
EXECUTABLE_RE = re.compile(r"(?i)\b(eval|exec|__import__|subprocess|os\.system)\b")


class PackError(ValueError):
    pass


def _walk_forbidden(obj: object, path: str = "") -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            lk = str(key).lower()
            if lk in FORBIDDEN_KEYS or str(key).startswith("!"):
                raise PackError(f"executable key rejected: {path}.{key}")
            _walk_forbidden(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _walk_forbidden(value, f"{path}[{i}]")
    elif isinstance(obj, str) and EXECUTABLE_RE.search(obj) and "def " in obj:
        raise PackError(f"executable payload rejected at {path}")


def pack_fingerprint(data: dict[str, Any]) -> str:
    blob = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# These names are authorization channels, not business classification dimensions.
RESERVED_DIMENSIONS = {"acl", "permissions", "roles", "grants", "security"}
_HARD_FIELDS = {"from_addr_regex", "folder", "recipient_role", "subject_regex"}

# These are fixed output-safety operations, not enterprise classification values.
# Business axis names and values remain entirely inside an administrator-selected Pack.
_EXCERPT_MODES = {"allow", "truncate_excerpt", "omit_excerpt", "reference_only"}
_EXCERPT_RESTRICTION = {
    "allow": 0,
    "truncate_excerpt": 1,
    "omit_excerpt": 2,
    "reference_only": 3,
}
_SAFE_EXCERPT_ACTION = {"mode": "reference_only"}


def _text(value: object, field: str, limit: int = 96) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise PackError(f"invalid {field}")


def _dimensions(value: object, *, multi: bool) -> None:
    if not isinstance(value, dict) or len(value) > 16:
        raise PackError("invalid classification dimensions")
    for key, values in value.items():
        _text(key, "dimension name", 64)
        if key.lower() in RESERVED_DIMENSIONS:
            raise PackError("authorization dimension rejected")
        if multi:
            if not isinstance(values, list) or len(values) > 8:
                raise PackError("invalid tag values")
            for item in values:
                _text(item, "tag value")
        else:
            _text(values, "axis value")


def _excerpt_action(action: object, field: str, *, require_reference_only: bool = False) -> None:
    if not isinstance(action, dict) or set(action) - {"mode", "max_chars"}:
        raise PackError(f"invalid {field}")
    mode = action.get("mode")
    if mode not in _EXCERPT_MODES:
        raise PackError(f"invalid {field} mode")
    if require_reference_only and mode != "reference_only":
        raise PackError(f"unsafe {field} default")
    if mode == "truncate_excerpt":
        limit = action.get("max_chars")
        if type(limit) is not int or not 1 <= limit <= 512:
            raise PackError(f"invalid {field} max_chars")
    elif "max_chars" in action:
        raise PackError(f"unexpected {field} max_chars")


def _output_policy(data: dict[str, Any]) -> None:
    """Validate a Pack-declared outbound excerpt policy, if one is supplied.

    Omission is valid and resolves to reference-only at the evidence boundary.  A
    declared default may not expose text: exposure needs an explicit axis/value
    rule, so a newly introduced business value remains fail-closed.
    """
    policy = data.get("output_policy")
    if policy is None:
        return
    if not isinstance(policy, dict) or set(policy) != {"excerpt"}:
        raise PackError("invalid output_policy")
    excerpt = policy.get("excerpt")
    if not isinstance(excerpt, dict) or set(excerpt) - {"default", "axes"} or "default" not in excerpt:
        raise PackError("invalid excerpt output_policy")
    _excerpt_action(excerpt["default"], "excerpt default", require_reference_only=True)
    axes = excerpt.get("axes", {})
    if not isinstance(axes, dict) or len(axes) > 16:
        raise PackError("invalid excerpt policy axes")
    for axis, values in axes.items():
        _text(axis, "excerpt policy axis", 64)
        if axis.lower() in RESERVED_DIMENSIONS:
            raise PackError("authorization dimension rejected")
        if not isinstance(values, dict) or len(values) > 64:
            raise PackError("invalid excerpt policy values")
        for value, action in values.items():
            _text(value, "excerpt policy value")
            _excerpt_action(action, "excerpt policy action")


def observation_excerpt_action(pack: dict[str, Any] | None, semantics: object) -> dict[str, Any]:
    """Choose the most restrictive Pack-declared action for semantic axes.

    A missing, malformed, or unmatched policy deliberately returns
    ``reference_only``.  This function has no knowledge of labels such as
    ``sensitivity`` or ``restricted``; those are Pack data rather than engine
    enums.  When several declared axes match, the stricter safety operation wins.
    """
    policy = (pack or {}).get("output_policy")
    excerpt = policy.get("excerpt") if isinstance(policy, dict) else None
    if not isinstance(excerpt, dict):
        return dict(_SAFE_EXCERPT_ACTION)
    default = excerpt.get("default")
    if not isinstance(default, dict) or default.get("mode") != "reference_only":
        return dict(_SAFE_EXCERPT_ACTION)
    axes = excerpt.get("axes", {})
    semantic_axes = semantics.get("axes", {}) if isinstance(semantics, dict) else {}
    if not isinstance(axes, dict) or not isinstance(semantic_axes, dict):
        return dict(default)
    selected: dict[str, Any] | None = None
    for axis, value in semantic_axes.items():
        actions = axes.get(axis)
        action = actions.get(value) if isinstance(actions, dict) and isinstance(value, str) else None
        if not isinstance(action, dict) or action.get("mode") not in _EXCERPT_RESTRICTION:
            continue
        if action.get("mode") == "truncate_excerpt" and (type(action.get("max_chars")) is not int or not 1 <= action["max_chars"] <= 512):
            continue
        if selected is None or _EXCERPT_RESTRICTION[action["mode"]] > _EXCERPT_RESTRICTION[selected["mode"]]:
            selected = action
    return copy.deepcopy(selected if selected is not None else default)


def _hint(hint: object) -> None:
    if not isinstance(hint, dict):
        raise PackError("semantic hint must be a mapping")
    utterances = hint.get("utterances", [])
    if not isinstance(utterances, list) or len(utterances) > 8:
        raise PackError("semantic utterances must be a bounded list")
    for utterance in utterances:
        _text(utterance, "semantic utterance", 512)
    low, high = hint.get("threshold_low", .55), hint.get("threshold_high", .82)
    if (any(type(x) not in (int, float) or not math.isfinite(x) for x in (low, high))
            or not 0 <= low < high <= 1):
        raise PackError("invalid semantic thresholds")


def _condition(condition: object) -> None:
    if not isinstance(condition, dict):
        raise PackError("event condition must be a mapping")
    if set(condition) - (_HARD_FIELDS | {"hard", "semantic"}):
        raise PackError("unsupported event condition")
    if "hard" in condition and set(condition) & _HARD_FIELDS:
        raise PackError("mixed hard condition forms")
    hard = condition.get("hard", {k: v for k, v in condition.items() if k in _HARD_FIELDS})
    if not isinstance(hard, dict) or set(hard) - _HARD_FIELDS:
        raise PackError("invalid hard condition")
    for key, value in hard.items():
        _text(value, "hard condition", 256)
        if key.endswith("_regex"):
            try:
                re.compile(value)
            except re.error:
                raise PackError("invalid condition regex") from None
    if "semantic" in condition:
        _hint(condition["semantic"])


def _classification(data: dict[str, Any]) -> None:
    classification = data.get("classification", {})
    if not isinstance(classification, dict):
        raise PackError("classification must be a mapping")
    types = classification.get("event_types", [])
    if not isinstance(types, list) or len(types) > 64:
        raise PackError("event_types must be a bounded list")
    ids = set()
    for spec in types:
        if not isinstance(spec, dict):
            raise PackError("event type must be a mapping")
        _text(spec.get("id"), "event type id")
        if spec["id"] in ids:
            raise PackError("duplicate event type id")
        ids.add(spec["id"])
        if "label" in spec:
            _text(spec["label"], "event label", 128)
        if type(spec.get("priority", 0)) is not int:
            raise PackError("priority must be an integer")
        # Legacy packs sometimes put the hard fields directly beside the type id.
        condition = spec.get("when", {k: v for k, v in spec.items() if k in _HARD_FIELDS | {"hard", "semantic"}})
        _condition(condition)
        _dimensions(spec.get("tags", {}), multi=True)
        _dimensions(spec.get("axes", {}), multi=False)
    defaults = classification.get("defaults", {})
    if not isinstance(defaults, dict) or defaults.get("broadcast", "reference") not in {"action_required", "watch", "reference"}:
        raise PackError("invalid attention default")
    hints = data.get("attention_hints", [])
    if not isinstance(hints, list) or len(hints) > 64:
        raise PackError("attention_hints must be a bounded list")
    for hint in hints:
        _hint(hint)


def validate_pack(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise PackError("pack must be a mapping")
    _walk_forbidden(data)
    _classification(data)
    _output_policy(data)
    data = copy.deepcopy(data)
    if not str(data.get("id") or "").strip():
        raise PackError("pack.id is required")
    data.setdefault("version", "0.0.0")
    data.setdefault("entities", [])
    data.setdefault("relations", [])
    data.setdefault("classification", {})
    data.setdefault("attention_hints", [])
    data.setdefault("routing_conditions", [])
    data.setdefault("action_policy", [])
    data["fingerprint"] = pack_fingerprint({k: v for k, v in data.items() if k != "fingerprint"})
    return data


def load_pack_file(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PackError(f"invalid pack: {path}")
    return validate_pack(raw)


def load_active_pack(state_root: Path, code_root: Path | None = None) -> dict[str, Any] | None:
    user = state_root / "packs" / "user.yaml"
    if user.is_file():
        return load_pack_file(user)
    root = code_root or Path(__file__).resolve().parents[1]
    minimal = root / "config" / "packs" / "minimal.yaml"
    if minimal.is_file():
        return load_pack_file(minimal)
    return None


def classification_catalog(pack: dict[str, Any] | None) -> dict[str, Any]:
    """Dynamic display/filter choices. This is not an authorization catalog."""
    types = ((pack or {}).get("classification") or {}).get("event_types", [])
    tags: dict[str, set[str]] = {}
    axes: dict[str, set[str]] = {}
    for spec in types:
        for key, values in spec.get("tags", {}).items():
            tags.setdefault(key, set()).update(values)
        for key, value in spec.get("axes", {}).items():
            axes.setdefault(key, set()).add(value)
    return {
        "pack": {k: (pack or {}).get(k) for k in ("id", "version", "fingerprint")},
        "event_types": [{"id": s["id"], "label": s.get("label", s["id"]), "priority": s.get("priority", 0)} for s in sorted(types, key=lambda s: s["id"])],
        "tags": {k: sorted(v) for k, v in sorted(tags.items())},
        "axes": {k: sorted(v) for k, v in sorted(axes.items())},
    }
