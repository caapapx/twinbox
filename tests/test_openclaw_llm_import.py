"""Tests for OpenClaw -> Twinbox LLM import mapping."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from twinbox_core.openclaw_llm_import import (
    OpenClawLlmImportError,
    import_llm_from_openclaw_dict,
    import_llm_from_openclaw_path,
)


def test_import_openai_completions_custom_provider() -> None:
    cfg = {
        "agents": {"defaults": {"model": {"primary": "custom-foo/astron-code-latest"}}},
        "models": {
            "providers": {
                "custom-foo": {
                    "baseUrl": "https://api.example.com/v2",
                    "apiKey": "secret-key",
                    "api": "openai-completions",
                    "models": [{"id": "astron-code-latest", "name": "x"}],
                }
            }
        },
    }
    got = import_llm_from_openclaw_dict(cfg)
    assert got["twinbox_provider"] == "openai"
    assert got["model"] == "astron-code-latest"
    assert got["api_url"] == "https://api.example.com/v2"
    assert got["api_key"] == "secret-key"


def test_import_missing_primary_raises() -> None:
    with pytest.raises(OpenClawLlmImportError):
        import_llm_from_openclaw_dict({"agents": {}, "models": {"providers": {}}})


def test_import_from_path_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "openclaw.json"
    p.write_text(
        json.dumps(
            {
                "agents": {"defaults": {"model": "p/m"}},
                "models": {
                    "providers": {
                        "p": {
                            "baseUrl": "https://h/v1",
                            "apiKey": "k",
                            "api": "openai-completions",
                            "models": [{"id": "m"}],
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    got = import_llm_from_openclaw_path(p)
    assert got["openclaw_model_ref"] == "p/m"
