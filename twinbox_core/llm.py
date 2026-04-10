"""LLM transport layer — zero external dependencies (urllib.request only).

Supports OpenAI-compatible and Anthropic backends.
Resolves config from twinbox.json (auto-imported from OpenClaw host).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class LLMError(RuntimeError):
    """Raised when twinbox cannot resolve or call an LLM backend."""


@dataclass(frozen=True)
class BackendConfig:
    backend: str
    model: str
    url: str
    api_key: str
    timeout: int
    retries: int


def resolve_backend() -> BackendConfig:
    """Resolve LLM backend from twinbox.json, then env vars."""
    from .config import load_config

    cfg = load_config()
    llm = cfg.get("llm", {})
    if isinstance(llm, dict) and llm.get("api_key"):
        provider = str(llm.get("provider", "openai") or "openai").lower()
        api_key = str(llm["api_key"])
        model = str(llm.get("model", "") or "")
        api_url = str(llm.get("api_url", "") or "")
        timeout = int(llm.get("timeout", 60) or 60)
        retries = int(llm.get("retries", 1) or 1)
        if provider == "anthropic":
            if not api_url:
                api_url = "https://api.anthropic.com"
            return BackendConfig("anthropic", model, f"{api_url.rstrip('/')}/v1/messages", api_key, timeout, retries)
        if not model or not api_url:
            raise LLMError("Incomplete LLM config in twinbox.json: need model and api_url")
        return BackendConfig("openai", model, api_url, api_key, timeout, retries)

    # Fallback to env vars
    if os.environ.get("LLM_API_KEY"):
        model = os.environ.get("LLM_MODEL", "").strip()
        url = os.environ.get("LLM_API_URL", "").strip()
        if not model or not url:
            raise LLMError("Set LLM_API_KEY, LLM_MODEL, and LLM_API_URL")
        return BackendConfig("openai", model, url, os.environ["LLM_API_KEY"],
                             int(os.environ.get("LLM_TIMEOUT", "60") or "60"),
                             int(os.environ.get("LLM_RETRIES", "1") or "1"))

    raise LLMError(
        "No LLM backend configured. Run `twinbox setup` to import from OpenClaw, "
        "or set LLM_API_KEY, LLM_MODEL, LLM_API_URL env vars."
    )


def _normalize_url(url: str) -> str:
    u = url.strip()
    if not u:
        return url
    if "chat/completions" in u.lower():
        return u
    return u.rstrip("/") + "/chat/completions"


def _request_once(prompt: str, max_tokens: int, system_prompt: str | None, config: BackendConfig) -> str:
    if config.backend == "openai":
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": [],
            "temperature": 0.15,
            "max_tokens": max_tokens,
        }
        if system_prompt:
            payload["messages"].append({"role": "system", "content": system_prompt})
        payload["messages"].append({"role": "user", "content": prompt})
        request = urllib.request.Request(
            _normalize_url(config.url),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {config.api_key}"},
            method="POST",
        )
    else:
        payload = {
            "model": config.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt
        request = urllib.request.Request(
            config.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-api-key": config.api_key, "anthropic-version": "2023-06-01"},
            method="POST",
        )

    with urllib.request.urlopen(request, timeout=config.timeout) as response:
        body = json.loads(response.read().decode("utf-8"))

    if body.get("error"):
        raise LLMError(f"API error: {json.dumps(body['error'], ensure_ascii=False)}")

    if config.backend == "openai":
        return str(body.get("choices", [{}])[0].get("message", {}).get("content", "{}"))

    content = body.get("content", [])
    return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict)) or "{}"


def call_llm(prompt: str, max_tokens: int = 4096, system_prompt: str | None = None) -> str:
    config = resolve_backend()
    last_error: Exception | None = None
    for attempt in range(config.retries + 1):
        try:
            return _request_once(prompt, max_tokens, system_prompt, config)
        except (LLMError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = exc
            if attempt >= config.retries:
                break
            time.sleep(3)
    raise LLMError(str(last_error) if last_error else "Unknown LLM failure")


def validate_backend() -> tuple[bool, str]:
    try:
        _request_once("ping", max_tokens=10, system_prompt=None, config=resolve_backend())
        return (True, "")
    except Exception as exc:
        return (False, str(exc))


# --- JSON repair helpers ---

def strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def extract_balanced_prefix(text: str) -> str:
    obj = text.find("{")
    arr = text.find("[")
    start = min(x for x in (obj, arr) if x != -1) if obj != -1 or arr != -1 else -1
    if start == -1:
        return text.strip()
    in_string = False
    escaped = False
    stack: list[str] = []
    last_balanced = -1
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in {"{", "["}:
            stack.append(char)
        elif char in {"}", "]"} and stack:
            last = stack[-1]
            if (char == "}" and last == "{") or (char == "]" and last == "["):
                stack.pop()
                if not stack:
                    last_balanced = index
    if last_balanced != -1:
        return text[start:last_balanced + 1].strip()
    return text[start:].strip()


def clean_json_text(raw: str) -> str:
    base = raw.lstrip("\ufeff").strip()
    fenced = strip_fences(base)
    extracted = extract_balanced_prefix(fenced)
    # Try parsing with progressive repair
    no_trailing = re.sub(r",\s*([}\]])", r"\1", extracted)
    for candidate in [base, fenced, extracted, no_trailing]:
        try:
            return json.dumps(json.loads(candidate), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            continue
    raise LLMError(f"JSON parse failed: {base[:200]}")
