"""Shared LLM transport, backend resolution, and JSON repair helpers."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .env_writer import load_env_file as _load_env_file


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


def load_env_file(path: str | os.PathLike[str] | None) -> dict[str, str]:
    if not path:
        return {}
    env_path = Path(path).expanduser()
    return _load_env_file(env_path)


def merged_env(
    env_file: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    merged = load_env_file(env_file)
    merged.update(env or os.environ)
    return merged


def _int_value(raw: str | None, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise LLMError(f"Invalid integer value: {raw}") from exc


def resolve_backend(
    env_file: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
) -> BackendConfig:
    resolved_env = merged_env(env_file=env_file, env=env)
    timeout = _int_value(resolved_env.get("LLM_TIMEOUT"), 180)
    retries = _int_value(resolved_env.get("LLM_RETRIES"), 2)

    if resolved_env.get("LLM_API_KEY"):
        model = resolved_env.get("LLM_MODEL", "").strip()
        url = resolved_env.get("LLM_API_URL", "").strip()
        if not model or not url:
            raise LLMError(
                "Incomplete OpenAI-compatible configuration. Set LLM_API_KEY, LLM_MODEL, and LLM_API_URL."
            )
        return BackendConfig(
            backend="openai",
            model=model,
            url=url,
            api_key=resolved_env["LLM_API_KEY"],
            timeout=timeout,
            retries=retries,
        )

    if resolved_env.get("ANTHROPIC_API_KEY"):
        model = resolved_env.get("ANTHROPIC_MODEL", "").strip()
        base_url = resolved_env.get("ANTHROPIC_BASE_URL", "").strip()
        if not model or not base_url:
            raise LLMError(
                "Incomplete Anthropic configuration. Set ANTHROPIC_API_KEY, ANTHROPIC_MODEL, and ANTHROPIC_BASE_URL."
            )
        return BackendConfig(
            backend="anthropic",
            model=model,
            url=f"{base_url.rstrip('/')}/v1/messages",
            api_key=resolved_env["ANTHROPIC_API_KEY"],
            timeout=timeout,
            retries=retries,
        )

    raise LLMError(
        "No LLM backend configured. "
        "OpenAI-compatible (HTTP POST to …/chat/completions + Bearer): set LLM_API_KEY, LLM_MODEL, and LLM_API_URL "
        "(base URL such as …/v2 is accepted; /chat/completions is appended when missing). "
        "Anthropic native (/v1/messages + x-api-key): set ANTHROPIC_API_KEY, ANTHROPIC_MODEL, and ANTHROPIC_BASE_URL."
    )


def normalize_openai_chat_completions_url(url: str) -> str:
    """If `url` is an OpenAI-compatible base (e.g. …/v1 or …/v2) without a path, append /chat/completions.

    Providers such as Some MaaS document only the base ``…/v2``; clients must POST to …/v2/chat/completions.
    Bare bases often return 401 from the gateway when hit directly.
    """
    u = url.strip()
    if not u:
        return url
    lower = u.lower()
    if "chat/completions" in lower:
        return u
    return u.rstrip("/") + "/chat/completions"


def backend_summary(config: BackendConfig) -> str:
    if config.backend == "openai":
        return f"LLM backend: OpenAI-compatible ({config.model})"
    return f"LLM backend: Anthropic API ({config.model})"


def validate_backend(config: BackendConfig) -> tuple[bool, str]:
    """Send a minimal test request to validate the LLM backend is reachable and configured correctly.

    Returns:
        (success: bool, error_message: str)
    """
    test_prompt = "ping"
    try:
        _request_once(test_prompt, max_tokens=10, system_prompt=None, config=config)
        return (True, "")
    except LLMError as exc:
        return (False, str(exc))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            payload = exc.read()
            if payload:
                body = payload.decode("utf-8", errors="replace").strip()
        except Exception:
            body = ""
        if body:
            return (False, f"Network error: {exc}; response body: {body}")
        return (False, f"Network error: {exc}")
    except (TimeoutError, urllib.error.URLError) as exc:
        return (False, f"Network error: {exc}")
    except Exception as exc:
        return (False, f"Unexpected error: {exc}")


def _request_once(
    prompt: str,
    max_tokens: int,
    system_prompt: str | None,
    config: BackendConfig,
) -> str:
    if config.backend == "openai":
        payload = {
            "model": config.model,
            "messages": [],
            "temperature": 0.15,
            "max_tokens": max_tokens,
        }
        if system_prompt:
            payload["messages"].append({"role": "system", "content": system_prompt})
        payload["messages"].append({"role": "user", "content": prompt})
        request_url = normalize_openai_chat_completions_url(config.url)
        request = urllib.request.Request(
            request_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key}",
            },
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
            headers={
                "Content-Type": "application/json",
                "x-api-key": config.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

    with urllib.request.urlopen(request, timeout=config.timeout) as response:
        body = json.loads(response.read().decode("utf-8"))

    if body.get("error"):
        raise LLMError(f"API error: {json.dumps(body['error'], ensure_ascii=False)}")

    if config.backend == "openai":
        return str(body.get("choices", [{}])[0].get("message", {}).get("content", "{}"))

    content = body.get("content", [])
    text_parts = [str(item.get("text", "")) for item in content if isinstance(item, dict)]
    return "".join(text_parts) or "{}"


def call_llm(
    prompt: str,
    max_tokens: int = 4096,
    system_prompt: str | None = None,
    *,
    env_file: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
    model_override: str | None = None,
) -> str:
    config = resolve_backend(env_file=env_file, env=env)
    if model_override:
        config = BackendConfig(
            backend=config.backend,
            model=model_override,
            url=config.url,
            api_key=config.api_key,
            timeout=config.timeout,
            retries=config.retries,
        )

    last_error: Exception | None = None
    for attempt in range(config.retries + 1):
        try:
            return _request_once(prompt, max_tokens, system_prompt, config)
        except (LLMError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            last_error = exc
            if attempt >= config.retries:
                break
            print(f"Retry {attempt + 1}/{config.retries}...", file=sys.stderr)
            time.sleep(5)

    raise LLMError(str(last_error) if last_error else "Unknown LLM failure")


def strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def find_json_start(text: str) -> int:
    obj = text.find("{")
    arr = text.find("[")
    if obj == -1:
        return arr
    if arr == -1:
        return obj
    return min(obj, arr)


def extract_balanced_prefix(text: str) -> str:
    start = find_json_start(text)
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
        return text[start : last_balanced + 1].strip()
    return text[start:].strip()


def remove_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)


def close_dangling_string(text: str) -> str:
    in_string = False
    escaped = False

    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True

    return f'{text}"' if in_string else text


def balance_closers(text: str) -> str:
    in_string = False
    escaped = False
    stack: list[str] = []

    for char in text:
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

    suffix = "".join("}" if item == "{" else "]" for item in reversed(stack))
    return text + suffix


def clean_json_text(raw: str) -> str:
    base = raw.lstrip("\ufeff").strip()
    candidates: list[str] = []

    def push(value: str) -> None:
        normalized = value.strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    fenced = strip_fences(base)
    extracted = extract_balanced_prefix(fenced)

    push(base)
    push(fenced)
    push(extracted)
    push(remove_trailing_commas(extracted))
    push(balance_closers(close_dangling_string(remove_trailing_commas(extracted))))

    last_error = "unknown"
    for candidate in candidates:
        try:
            return json.dumps(json.loads(candidate), ensure_ascii=False, indent=2)
        except json.JSONDecodeError as exc:
            last_error = exc.msg

    preview = " ".join(base.split())[:500]
    if preview:
        print(f"Raw (first 500): {preview}", file=sys.stderr)
    raise LLMError(f"JSON parse failed after repair attempts: {last_error}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser("backend-summary")
    summary.add_argument("--env-file")

    call = subparsers.add_parser("call")
    call.add_argument("--env-file")
    call.add_argument("--prompt-file", required=True)
    call.add_argument("--system-prompt-file")
    call.add_argument("--max-tokens", type=int, default=4096)
    call.add_argument("--model")

    clean = subparsers.add_parser("clean-json")
    clean.add_argument("--input-file")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "backend-summary":
            print(backend_summary(resolve_backend(env_file=args.env_file)))
            return 0

        if args.command == "call":
            prompt = Path(args.prompt_file).read_text(encoding="utf-8")
            system_prompt = None
            if args.system_prompt_file:
                system_prompt = Path(args.system_prompt_file).read_text(encoding="utf-8")
            try:
                print(
                    call_llm(
                        prompt,
                        max_tokens=args.max_tokens,
                        system_prompt=system_prompt,
                        env_file=args.env_file,
                        model_override=args.model,
                    )
                )
            except LLMError as exc:
                print(str(exc), file=sys.stderr)
                print("{}")
            return 0

        if args.command == "clean-json":
            raw = Path(args.input_file).read_text(encoding="utf-8") if args.input_file else sys.stdin.read()
            try:
                print(clean_json_text(raw))
            except LLMError as exc:
                print(str(exc), file=sys.stderr)
                print("{}")
            return 0
    except LLMError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
