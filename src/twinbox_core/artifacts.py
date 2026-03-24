"""Helpers for writing timestamped artifact files."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def generated_at() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def yaml_string(value: object) -> str:
    if value is None:
        value = ""
    return json.dumps(str(value), ensure_ascii=False)


def write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
