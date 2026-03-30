"""Single-source Twinbox configuration stored in twinbox.json."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "twinbox.json"


def config_path_for_state_root(state_root: Path) -> Path:
    return state_root / CONFIG_FILENAME


def config_path_for_env_file(env_path: Path) -> Path:
    return env_path.parent / CONFIG_FILENAME


def _load_legacy_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def load_twinbox_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"version": 1}
    payload = deepcopy(payload)
    payload.setdefault("version", 1)
    return payload


def save_twinbox_config(path: Path, config: dict[str, Any]) -> None:
    payload = deepcopy(config)
    payload.setdefault("version", 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mask_secret(value: str) -> str:
    if len(value) < 6:
        return "***"
    return f"***...{value[-4:]}"


def config_from_env(env: dict[str, str]) -> dict[str, Any]:
    config: dict[str, Any] = {"version": 1}

    mailbox_keys = {
        "MAIL_ADDRESS",
        "MAIL_ACCOUNT_NAME",
        "MAIL_DISPLAY_NAME",
        "IMAP_HOST",
        "IMAP_PORT",
        "IMAP_ENCRYPTION",
        "IMAP_LOGIN",
        "IMAP_PASS",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_ENCRYPTION",
        "SMTP_LOGIN",
        "SMTP_PASS",
    }
    if any(env.get(key) for key in mailbox_keys):
        config["mailbox"] = {
            "email": env.get("MAIL_ADDRESS", ""),
            "account_name": env.get("MAIL_ACCOUNT_NAME", ""),
            "display_name": env.get("MAIL_DISPLAY_NAME", ""),
            "imap": {
                "host": env.get("IMAP_HOST", ""),
                "port": env.get("IMAP_PORT", ""),
                "encryption": env.get("IMAP_ENCRYPTION", ""),
                "login": env.get("IMAP_LOGIN", ""),
                "password": env.get("IMAP_PASS", ""),
            },
            "smtp": {
                "host": env.get("SMTP_HOST", ""),
                "port": env.get("SMTP_PORT", ""),
                "encryption": env.get("SMTP_ENCRYPTION", ""),
                "login": env.get("SMTP_LOGIN", ""),
                "password": env.get("SMTP_PASS", ""),
            },
        }

    llm_provider = ""
    if env.get("LLM_API_KEY") or env.get("LLM_MODEL") or env.get("LLM_API_URL"):
        llm_provider = "openai"
    elif env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_MODEL") or env.get("ANTHROPIC_BASE_URL"):
        llm_provider = "anthropic"
    if llm_provider:
        if llm_provider == "anthropic":
            api_key = env.get("ANTHROPIC_API_KEY", "")
            model = env.get("ANTHROPIC_MODEL", "")
            api_url = env.get("ANTHROPIC_BASE_URL", "")
        else:
            api_key = env.get("LLM_API_KEY", "")
            model = env.get("LLM_MODEL", "")
            api_url = env.get("LLM_API_URL", "")
        config["llm"] = {
            "provider": llm_provider,
            "api_key": api_key,
            "model": model,
            "api_url": api_url,
        }
        if env.get("LLM_TIMEOUT", ""):
            config["llm"]["timeout"] = env["LLM_TIMEOUT"]
        if env.get("LLM_RETRIES", ""):
            config["llm"]["retries"] = env["LLM_RETRIES"]

    return config


def _first_llm_str(llm: dict[str, Any], *keys: str) -> str:
    for key in keys:
        raw = llm.get(key)
        if raw is None:
            continue
        s = str(raw).strip()
        if s:
            return s
    return ""


def _normalized_openai_llm_fields(llm: dict[str, Any]) -> tuple[str, str, str]:
    """Map vendor / console export keys into canonical OpenAI-compat triple."""
    api_key = _first_llm_str(
        llm,
        "api_key",
        "APIKey",
        "apiKey",
        "apikey",
    )
    model = _first_llm_str(llm, "model", "modelId", "model_id")
    api_url = _first_llm_str(
        llm,
        "api_url",
        "apiUrl",
        "openai_url",
        "openaiUrl",
        "base_url",
        "baseURL",
        "baseUrl",
    )
    return api_key, model, api_url


def env_from_twinbox_config(config: dict[str, Any]) -> dict[str, str]:
    env: dict[str, str] = {}
    mailbox = config.get("mailbox") if isinstance(config.get("mailbox"), dict) else {}
    if mailbox:
        imap = mailbox.get("imap") if isinstance(mailbox.get("imap"), dict) else {}
        smtp = mailbox.get("smtp") if isinstance(mailbox.get("smtp"), dict) else {}
        mapping = {
            "MAIL_ADDRESS": mailbox.get("email", ""),
            "MAIL_ACCOUNT_NAME": mailbox.get("account_name", ""),
            "MAIL_DISPLAY_NAME": mailbox.get("display_name", ""),
            "IMAP_HOST": imap.get("host", ""),
            "IMAP_PORT": str(imap.get("port", "") or ""),
            "IMAP_ENCRYPTION": imap.get("encryption", ""),
            "IMAP_LOGIN": imap.get("login", ""),
            "IMAP_PASS": imap.get("password", ""),
            "SMTP_HOST": smtp.get("host", ""),
            "SMTP_PORT": str(smtp.get("port", "") or ""),
            "SMTP_ENCRYPTION": smtp.get("encryption", ""),
            "SMTP_LOGIN": smtp.get("login", ""),
            "SMTP_PASS": smtp.get("password", ""),
        }
        env.update({key: value for key, value in mapping.items() if value not in ("", None)})

    llm = config.get("llm") if isinstance(config.get("llm"), dict) else {}
    provider = str(llm.get("provider", "") or "").strip().lower()
    oa_key, oa_model, oa_url = _normalized_openai_llm_fields(llm)
    if provider not in ("openai", "anthropic") and oa_key and oa_model and oa_url:
        provider = "openai"
    if provider == "anthropic":
        mapping = {
            "ANTHROPIC_API_KEY": _first_llm_str(llm, "api_key", "APIKey", "apiKey"),
            "ANTHROPIC_MODEL": _first_llm_str(llm, "model", "modelId", "model_id"),
            "ANTHROPIC_BASE_URL": _first_llm_str(
                llm, "api_url", "apiUrl", "base_url", "baseURL", "baseUrl"
            ),
        }
    elif provider == "openai":
        mapping = {
            "LLM_API_KEY": oa_key,
            "LLM_MODEL": oa_model,
            "LLM_API_URL": oa_url,
        }
    else:
        mapping = {}
    env.update({key: str(value) for key, value in mapping.items() if value not in ("", None)})
    if llm.get("timeout", "") not in ("", None):
        env["LLM_TIMEOUT"] = str(llm["timeout"])
    if llm.get("retries", "") not in ("", None):
        env["LLM_RETRIES"] = str(llm["retries"])
    return env


def load_config_or_legacy(env_path: Path) -> dict[str, Any]:
    if env_path.name == "twinbox.json":
        if env_path.exists():
            return load_twinbox_config(env_path)
        return {"version": 1}
    config_path = config_path_for_env_file(env_path)
    if config_path.exists():
        return load_twinbox_config(config_path)
    legacy = _load_legacy_env(env_path)
    if legacy:
        return config_from_env(legacy)
    return {"version": 1}


def write_env_as_twinbox_config(env_path: Path, env: dict[str, str]) -> Path:
    """Merge *env* into ``twinbox.json``.

    *env_path* may be ``state_root/twinbox.json`` (preferred) or legacy
    ``state_root/.env`` (resolved to the JSON path next to it).
    """
    if env_path.name == "twinbox.json":
        config_path = env_path
        existing: dict[str, Any] = load_twinbox_config(config_path) if config_path.exists() else {"version": 1}
    else:
        config_path = config_path_for_env_file(env_path)
        existing = load_config_or_legacy(env_path)
    merged = deepcopy(existing)
    env_config = config_from_env(env)
    for key, value in env_config.items():
        if key == "version":
            continue
        merged[key] = value
    save_twinbox_config(config_path, merged)
    if env_path.name == ".env" and env_path.exists():
        try:
            env_path.unlink()
        except OSError:
            pass
    return config_path


def load_masked_twinbox_config(path: Path) -> dict[str, Any]:
    payload = load_twinbox_config(path)
    llm = payload.get("llm")
    if isinstance(llm, dict) and llm.get("api_key"):
        llm = dict(llm)
        llm["api_key_masked"] = mask_secret(str(llm.get("api_key", "")))
        llm.pop("api_key", None)
        payload["llm"] = llm
    mailbox = payload.get("mailbox")
    if isinstance(mailbox, dict):
        mailbox = deepcopy(mailbox)
        for section in ("imap", "smtp"):
            inner = mailbox.get(section)
            if isinstance(inner, dict) and inner.get("password"):
                inner = dict(inner)
                inner["password_masked"] = mask_secret(str(inner.get("password", "")))
                inner.pop("password", None)
                mailbox[section] = inner
        payload["mailbox"] = mailbox
    return payload
