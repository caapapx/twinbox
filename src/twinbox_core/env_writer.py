"""Unified .env file read/write helpers for twinbox configuration."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .twinbox_config import (
    config_path_for_env_file,
    env_from_twinbox_config,
    load_config_or_legacy,
    write_env_as_twinbox_config,
)


def mask_secret(value: str) -> str:
    """Mask a secret value for display.

    'sk-abcdef...xyz1234' -> '***...1234'
    Short values (<6 chars) are fully masked.
    """
    if len(value) < 6:
        return "***"
    return f"***...{value[-4:]}"


def load_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict.

    Supports:
    - # comment lines
    - export KEY=VALUE prefix
    - single/double quoted values
    - KEY=VALUE without quotes
    """
    if path.name == ".env":
        config_path = config_path_for_env_file(path)
        if config_path.exists():
            return env_from_twinbox_config(load_config_or_legacy(path))

    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def merge_env_file(path: Path, updates: dict[str, str]) -> dict[str, str]:
    """Read existing .env and overlay updates. Returns merged dict.

    Keys not in updates are preserved from the existing file.
    """
    existing = load_env_file(path)
    merged = dict(existing)
    merged.update(updates)
    return merged


def write_env_file(path: Path, env: dict[str, str]) -> None:
    """Atomically write env dict to path as a .env file.

    - Values containing spaces or special chars are double-quoted.
    - File is written via tmp+rename for atomicity.
    - chmod 0600 applied.
    """
    if path.name == ".env":
        write_env_as_twinbox_config(path, env)
        return

    lines: list[str] = []
    for key, value in env.items():
        # Quote values that contain spaces, quotes, or shell metacharacters
        if any(c in value for c in (' ', '"', "'", '$', '\\', '\n', '\t', '#', '=')):
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            lines.append(f'{key}="{escaped}"')
        else:
            lines.append(f"{key}={value}")
    content = "\n".join(lines) + ("\n" if lines else "")

    path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write: write to a tmp file in the same dir, then rename
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
