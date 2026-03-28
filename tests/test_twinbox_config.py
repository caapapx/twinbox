"""Tests for twinbox.json <-> env mapping (vendor field aliases)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from twinbox_core.twinbox_config import env_from_twinbox_config, load_twinbox_config
from twinbox_core.llm import resolve_backend


def test_env_from_twinbox_config_vendor_llm_aliases_without_provider(tmp_path: Path) -> None:
    cfg_path = tmp_path / "twinbox.json"
    cfg_path.write_text(
        json.dumps(
            {
                "version": 1,
                "llm": {
                    "APIKey": "appid:secret_tail",
                    "modelId": "astron-code-latest",
                    "openai_url": "https://maas-coding-api.cn-huabei-1.xf-yun.com/v2",
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    env = env_from_twinbox_config(load_twinbox_config(cfg_path))
    assert env["LLM_API_KEY"] == "appid:secret_tail"
    assert env["LLM_MODEL"] == "astron-code-latest"
    assert env["LLM_API_URL"] == "https://maas-coding-api.cn-huabei-1.xf-yun.com/v2"


def test_env_from_twinbox_config_colon_api_key_unchanged(tmp_path: Path) -> None:
    key = "18d405aa28be3cbaeec5dee79d781627:YWQ4NmYzYjVmNTc4MWNhYjIyZjBlYzY1"
    cfg_path = tmp_path / "twinbox.json"
    cfg_path.write_text(
        json.dumps(
            {
                "version": 1,
                "llm": {
                    "provider": "openai",
                    "api_key": key,
                    "model": "m",
                    "api_url": "https://example.com/v2",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    env = env_from_twinbox_config(load_twinbox_config(cfg_path))
    assert env["LLM_API_KEY"] == key


def test_resolve_backend_reads_twinbox_json_with_vendor_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
    env_path = tmp_path / ".env"
    (tmp_path / "twinbox.json").write_text(
        json.dumps(
            {
                "version": 1,
                "llm": {
                    "APIKey": "x",
                    "modelId": "m",
                    "openai_url": "https://example.com/v2",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cfg = resolve_backend(env_file=env_path, env={})
    assert cfg.api_key == "x"
    assert cfg.model == "m"
    assert cfg.url == "https://example.com/v2"
