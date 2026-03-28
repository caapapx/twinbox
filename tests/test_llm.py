"""Tests for twinbox_core.llm — LLM backend resolution and JSON repair.

Critical correctness bar: clean_json_text must produce output that
json.loads() accepts without error. Asserting substring presence alone
is insufficient.
"""

from __future__ import annotations

import json
from io import BytesIO
import urllib.error

import pytest

from twinbox_core import llm as llm_module
from twinbox_core.llm import BackendConfig, clean_json_text, normalize_openai_chat_completions_url, resolve_backend, validate_backend


class TestNormalizeOpenAIChatUrl:
    def test_appends_chat_completions_to_v2_base(self) -> None:
        assert (
            normalize_openai_chat_completions_url("https://maas-coding-api.cn-huabei-1.xf-yun.com/v2")
            == "https://maas-coding-api.cn-huabei-1.xf-yun.com/v2/chat/completions"
        )

    def test_trailing_slash_stripped_before_append(self) -> None:
        assert (
            normalize_openai_chat_completions_url("https://example.com/v1/")
            == "https://example.com/v1/chat/completions"
        )

    def test_unchanged_when_already_has_chat_completions(self) -> None:
        u = "https://example.com/v1/chat/completions"
        assert normalize_openai_chat_completions_url(u) == u


class TestResolveBackend:
    """Backend config is built correctly from environment variables."""

    def test_openai_compatible_settings(self):
        backend = resolve_backend(
            env={
                "LLM_API_KEY": "test-key",
                "LLM_MODEL": "test-model",
                "LLM_API_URL": "https://example.com/v1/chat/completions",
                "LLM_TIMEOUT": "42",
                "LLM_RETRIES": "3",
            }
        )
        assert backend.backend == "openai"
        assert backend.model == "test-model"
        assert backend.url == "https://example.com/v1/chat/completions"
        assert backend.timeout == 42   # string → int conversion
        assert backend.retries == 3    # string → int conversion

    def test_timeout_and_retries_are_integers(self):
        """LLM_TIMEOUT and LLM_RETRIES must be converted from str to int."""
        backend = resolve_backend(
            env={
                "LLM_API_KEY": "k",
                "LLM_MODEL": "m",
                "LLM_API_URL": "https://example.com/v1/chat/completions",
                "LLM_TIMEOUT": "10",
                "LLM_RETRIES": "2",
            }
        )
        assert isinstance(backend.timeout, int)
        assert isinstance(backend.retries, int)

    def test_openai_requires_explicit_model_and_url(self):
        with pytest.raises(RuntimeError):
            resolve_backend(
                env={
                    "LLM_API_KEY": "k",
                }
            )


class TestValidateBackend:
    def test_http_error_includes_response_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = BackendConfig(
            backend="openai",
            model="test-model",
            url="https://example.com/v1/chat/completions",
            api_key="test-key",
            timeout=5,
            retries=0,
        )
        err = urllib.error.HTTPError(
            url=backend.url,
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"error":"Invalid authorization header"}'),
        )

        def _raise_once(*args, **kwargs):
            raise err

        monkeypatch.setattr(llm_module, "_request_once", _raise_once)
        ok, message = validate_backend(backend)
        assert ok is False
        assert "HTTP Error 401: Unauthorized" in message
        assert "response body" in message
        assert "Invalid authorization header" in message


class TestCleanJsonText:
    """clean_json_text must produce output that json.loads() accepts."""

    def _assert_valid_json(self, raw: str) -> dict | list:
        """Clean raw text and assert the result is valid JSON; return parsed value."""
        cleaned = clean_json_text(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"clean_json_text output is not valid JSON.\n"
                f"Input:   {raw!r}\n"
                f"Cleaned: {cleaned!r}\n"
                f"Error:   {exc}"
            )

    def test_removes_markdown_fence_and_trailing_commas(self):
        raw = """\
```json
{
  "items": [
    {"id": "1", "intent": "human",},
  ],
}
```"""
        parsed = self._assert_valid_json(raw)
        assert parsed["items"][0]["intent"] == "human"

    def test_already_valid_json_passes_through_unchanged(self):
        raw = '{"key": "value", "count": 3}'
        parsed = self._assert_valid_json(raw)
        assert parsed["key"] == "value"

    def test_removes_fence_without_trailing_commas(self):
        raw = '```json\n{"result": true}\n```'
        parsed = self._assert_valid_json(raw)
        assert parsed["result"] is True

    def test_handles_nested_trailing_commas(self):
        raw = '{"outer": {"inner": [1, 2,],},}'
        parsed = self._assert_valid_json(raw)
        assert parsed["outer"]["inner"] == [1, 2]

    def test_handles_array_root(self):
        raw = '```json\n[{"a": 1,}, {"b": 2,}]\n```'
        parsed = self._assert_valid_json(raw)
        assert len(parsed) == 2
