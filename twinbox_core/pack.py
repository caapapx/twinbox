"""Semantic Pack load / validate / fingerprint."""

from __future__ import annotations

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


def validate_pack(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise PackError("pack must be a mapping")
    _walk_forbidden(data)
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
