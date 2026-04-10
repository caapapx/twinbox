"""Twinbox configuration: twinbox.json + OpenClaw host LLM import."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

STATE_ROOT = Path.home() / ".twinbox"
CONFIG_FILENAME = "twinbox.json"


def state_root() -> Path:
    raw = os.environ.get("TWINBOX_STATE_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return STATE_ROOT


def config_path() -> Path:
    return state_root() / CONFIG_FILENAME


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {"version": 1}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"version": 1}
    payload.setdefault("version", 1)
    return deepcopy(payload)


def save_config(cfg: dict[str, Any]) -> None:
    payload = deepcopy(cfg)
    payload.setdefault("version", 1)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mask_secret(value: str) -> str:
    if len(value) < 6:
        return "***"
    return f"***...{value[-4:]}"


def imap_config_from_env() -> dict[str, Any]:
    """Build IMAP connection config from environment variables."""
    return {
        "host": os.environ.get("IMAP_HOST", "").strip(),
        "port": int(os.environ.get("IMAP_PORT", "993").strip() or "993"),
        "login": os.environ.get("IMAP_LOGIN", "").strip(),
        "password": os.environ.get("IMAP_PASS", "").strip(),
        "encryption": os.environ.get("IMAP_ENCRYPTION", "tls").strip(),
    }


def imap_config_from_config() -> dict[str, Any]:
    """Build IMAP connection config from twinbox.json."""
    cfg = load_config()
    mailbox = cfg.get("mailbox", {})
    if not isinstance(mailbox, dict):
        return {}
    imap = mailbox.get("imap", {})
    if not isinstance(imap, dict):
        return {}
    return {
        "host": str(imap.get("host", "") or ""),
        "port": int(imap.get("port", 993) or 993),
        "login": str(imap.get("login", "") or ""),
        "password": str(imap.get("password", "") or ""),
        "encryption": str(imap.get("encryption", "tls") or "tls"),
    }


def resolve_imap_config() -> dict[str, Any]:
    """Resolve IMAP config: env vars take precedence over twinbox.json."""
    env_cfg = imap_config_from_env()
    if env_cfg.get("host") and env_cfg.get("login"):
        return env_cfg
    file_cfg = imap_config_from_config()
    if file_cfg.get("host") and file_cfg.get("login"):
        return file_cfg
    return env_cfg  # return partial env for error reporting


def owner_email() -> str:
    env_val = os.environ.get("MAIL_ADDRESS", "").strip()
    if env_val:
        return env_val
    cfg = load_config()
    mailbox = cfg.get("mailbox", {})
    if isinstance(mailbox, dict):
        return str(mailbox.get("email", "") or "")
    return ""


def import_llm_from_openclaw() -> dict[str, Any]:
    """Read LLM config from ~/.openclaw/openclaw.json and write to twinbox.json."""
    openclaw_path = Path.home() / ".openclaw" / "openclaw.json"
    if not openclaw_path.exists():
        return {"ok": False, "error": "openclaw.json not found"}

    try:
        oc = json.loads(openclaw_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "error": str(exc)}

    agents = oc.get("agents", {})
    if not isinstance(agents, dict):
        return {"ok": False, "error": "agents section not found in openclaw.json"}

    defaults = agents.get("defaults", {})
    if not isinstance(defaults, dict):
        return {"ok": False, "error": "agents.defaults not found"}

    model_cfg = defaults.get("model", {})
    if not isinstance(model_cfg, dict):
        return {"ok": False, "error": "agents.defaults.model not found"}

    provider = model_cfg.get("provider", {})
    if not isinstance(provider, dict):
        return {"ok": False, "error": "model.provider not found"}

    api_key = str(provider.get("apiKey", "") or provider.get("APIKey", "") or "")
    base_url = str(provider.get("baseUrl", "") or provider.get("baseURL", "") or "")
    model_id = str(model_cfg.get("modelId", "") or model_cfg.get("model", "") or "")

    if not api_key:
        return {"ok": False, "error": "No apiKey found in openclaw model config"}

    cfg = load_config()
    cfg["llm"] = {
        "provider": "openai",
        "api_key": api_key,
        "model": model_id,
        "api_url": base_url,
    }
    save_config(cfg)
    return {
        "ok": True,
        "model": model_id,
        "api_url": base_url,
        "api_key_masked": mask_secret(api_key),
    }


def setup_from_env() -> dict[str, Any]:
    """Setup twinbox.json from environment variables (IMAP + LLM from OpenClaw)."""
    imap_cfg = resolve_imap_config()
    email = owner_email()

    result: dict[str, Any] = {"ok": True, "steps": []}

    # Write mailbox config
    if imap_cfg.get("host") and imap_cfg.get("login") and imap_cfg.get("password"):
        cfg = load_config()
        cfg["mailbox"] = {
            "email": email,
            "imap": {
                "host": imap_cfg["host"],
                "port": imap_cfg["port"],
                "encryption": imap_cfg.get("encryption", "tls"),
                "login": imap_cfg["login"],
                "password": imap_cfg["password"],
            },
        }
        save_config(cfg)
        result["steps"].append("mailbox_configured")
    else:
        result["steps"].append("mailbox_skipped_incomplete")

    # Import LLM from OpenClaw
    llm_result = import_llm_from_openclaw()
    if llm_result.get("ok"):
        result["steps"].append("llm_imported_from_openclaw")
        result["llm"] = {k: v for k, v in llm_result.items() if k != "ok"}
    else:
        result["steps"].append(f"llm_skip: {llm_result.get('error', 'unknown')}")

    return result
