"""Tests for openclaw_json_io."""

from __future__ import annotations

from pathlib import Path

import pytest

from twinbox_core.openclaw_json_io import (
    default_openclaw_fragment_path,
    load_openclaw_json,
    load_openclaw_json_with_file_ops,
    parse_openclaw_json_text,
)


def test_default_openclaw_fragment_path() -> None:
    root = Path("/repo")
    assert default_openclaw_fragment_path(root) == root / "openclaw-skill" / "openclaw.fragment.json"


def test_load_openclaw_json_missing_returns_empty(tmp_path: Path) -> None:
    assert load_openclaw_json(tmp_path / "nope.json") == {}


def test_load_openclaw_json_invalid_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_openclaw_json(p)


def test_parse_openclaw_json_text_ok(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    d = parse_openclaw_json_text(p, '{"a": 1}')
    assert d == {"a": 1}


def test_load_openclaw_json_with_file_ops_uses_fake_ops(tmp_path: Path) -> None:
    class _Fake:
        def is_file(self, path: Path) -> bool:
            return path.name == "exists.json"

        def read_text(self, path: Path, encoding: str = "utf-8") -> str:
            return '{"k": true}'

    p = tmp_path / "exists.json"
    assert load_openclaw_json_with_file_ops(_Fake(), p) == {"k": True}
    assert load_openclaw_json_with_file_ops(_Fake(), tmp_path / "missing.json") == {}
