"""Filesystem helpers for OpenClaw JSON configs (fragment + host ``openclaw.json``)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .openclaw_deploy_runtime import LocalFileOps


def default_openclaw_fragment_path(code_root: Path) -> Path:
    return code_root / "openclaw-skill" / "openclaw.fragment.json"


def parse_openclaw_json_text(path: Path, text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    return data


def load_openclaw_json_with_file_ops(file_ops: LocalFileOps | Any, path: Path) -> dict[str, Any]:
    if not file_ops.is_file(path):
        return {}
    return parse_openclaw_json_text(path, file_ops.read_text(path, encoding="utf-8"))


def load_openclaw_json(path: Path) -> dict[str, Any]:
    return load_openclaw_json_with_file_ops(LocalFileOps(), path)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    LocalFileOps().write_json_atomic(path, data)
