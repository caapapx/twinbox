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


def get_weknora_config() -> dict[str, bool]:
    """Return the safe public WeKnora setting without projecting provider details.

    No currently tracked configuration can mark a provider/API as verified.  The
    ADR-004 capability and live-service gates remain external human decisions,
    so this helper exposes a requested enable flag separately from actual live
    operation availability.  ``adr_004_accepted`` is read here (default False)
    so the live gate in ``weknora_http.live_authorized`` has a config source;
    flipping it requires an explicit owner-signed config change, never code.
    """
    raw = load_config().get("weknora")
    enabled = isinstance(raw, dict) and raw.get("enabled") is True
    adr_accepted = isinstance(raw, dict) and raw.get("adr_004_accepted") is True
    return {
        "enabled": enabled,
        "adr_004_accepted": adr_accepted,
        "provider_port_verified": False,
        "live_operations_available": False,
    }


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
        upsert_account(
            account_id=DEFAULT_ACCOUNT_ID,
            email=email,
            account_type="personal",
            host=str(imap_cfg["host"]),
            port=int(imap_cfg["port"]),
            login=str(imap_cfg["login"]),
            password=str(imap_cfg["password"]),
            encryption=str(imap_cfg.get("encryption") or "tls"),
            make_default=True,
        )
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


# --- Multi-account registry (legacy mailbox remains default) ---

DEFAULT_ACCOUNT_ID = "default"
_ACCOUNT_ID_RE = __import__("re").compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def _safe_account_id(account_id: str) -> str:
    aid = (account_id or "").strip()
    if not aid or not _ACCOUNT_ID_RE.match(aid):
        raise ValueError("account_id must be 1-64 chars: letters, digits, . _ -")
    return aid


def default_account_id() -> str:
    cfg = load_config()
    raw = str(cfg.get("default_account_id") or DEFAULT_ACCOUNT_ID).strip()
    return raw or DEFAULT_ACCOUNT_ID


def account_state_root(account_id: str | None = None) -> Path:
    """Per-account state namespace. Legacy default keeps files at state_root()."""
    aid = (account_id or default_account_id()).strip() or DEFAULT_ACCOUNT_ID
    if aid == DEFAULT_ACCOUNT_ID:
        return state_root()
    return state_root() / "accounts" / _safe_account_id(aid)


def _legacy_account_from_mailbox(cfg: dict[str, Any]) -> dict[str, Any] | None:
    mailbox = cfg.get("mailbox")
    if not isinstance(mailbox, dict):
        return None
    imap = mailbox.get("imap") if isinstance(mailbox.get("imap"), dict) else {}
    host = str(imap.get("host") or "")
    login = str(imap.get("login") or "")
    if not host and not login and not mailbox.get("email"):
        return None
    password = str(imap.get("password") or "")
    return {
        "account_id": DEFAULT_ACCOUNT_ID,
        "type": "personal",
        "email": str(mailbox.get("email") or login or ""),
        "provider": "imap",
        "imap": {
            "host": host,
            "port": int(imap.get("port") or 993),
            "encryption": str(imap.get("encryption") or "tls"),
            "login": login,
        },
        "password_set": bool(password),
        "_legacy_password": password,
    }


def list_accounts(*, include_secrets_flags: bool = True) -> list[dict[str, Any]]:
    """Public account metadata only (password_set boolean, never password)."""
    from . import vault

    cfg = load_config()
    rows: list[dict[str, Any]] = []
    accounts = cfg.get("accounts")
    if isinstance(accounts, list) and accounts:
        for raw in accounts:
            if not isinstance(raw, dict):
                continue
            aid = str(raw.get("account_id") or "").strip()
            if not aid:
                continue
            imap = raw.get("imap") if isinstance(raw.get("imap"), dict) else {}
            item = {
                "account_id": aid,
                "type": str(raw.get("type") or "personal"),
                "email": str(raw.get("email") or ""),
                "provider": str(raw.get("provider") or "imap"),
                "imap": {
                    "host": str(imap.get("host") or ""),
                    "port": int(imap.get("port") or 993),
                    "encryption": str(imap.get("encryption") or "tls"),
                    "login": str(imap.get("login") or ""),
                },
            }
            if include_secrets_flags:
                item["password_set"] = vault.has_secret(aid, "password") or bool(imap.get("password"))
            rows.append(item)
        return rows

    legacy = _legacy_account_from_mailbox(cfg)
    if legacy:
        public = {k: v for k, v in legacy.items() if not k.startswith("_")}
        if include_secrets_flags:
            public["password_set"] = bool(legacy.get("_legacy_password")) or vault.has_secret(
                DEFAULT_ACCOUNT_ID, "password"
            )
        return [public]
    return []


def get_account(account_id: str | None = None) -> dict[str, Any] | None:
    aid = (account_id or default_account_id()).strip() or DEFAULT_ACCOUNT_ID
    for row in list_accounts():
        if row.get("account_id") == aid:
            return row
    return None


def upsert_account(
    *,
    account_id: str,
    email: str = "",
    account_type: str = "personal",
    host: str = "",
    port: int = 993,
    login: str = "",
    password: str = "",
    encryption: str = "tls",
    provider: str = "imap",
    make_default: bool = False,
) -> dict[str, Any]:
    """Register/update an account; password goes to vault, never returned."""
    from . import vault

    aid = _safe_account_id(account_id)
    if account_type not in {"personal", "shared", "robot"}:
        raise ValueError("type must be personal|shared|robot")
    cfg = load_config()
    accounts = cfg.get("accounts")
    if not isinstance(accounts, list):
        accounts = []
        # Promote legacy mailbox into accounts[] once when creating the registry.
        legacy = _legacy_account_from_mailbox(cfg)
        if legacy:
            accounts.append(
                {
                    "account_id": DEFAULT_ACCOUNT_ID,
                    "type": "personal",
                    "email": legacy.get("email") or "",
                    "provider": "imap",
                    "imap": legacy.get("imap") or {},
                }
            )
            legacy_pw = str(legacy.get("_legacy_password") or "")
            if legacy_pw:
                vault.set_secret(DEFAULT_ACCOUNT_ID, "password", legacy_pw)
                mailbox = cfg.get("mailbox")
                if isinstance(mailbox, dict) and isinstance(mailbox.get("imap"), dict):
                    mailbox["imap"].pop("password", None)

    found = False
    for row in accounts:
        if not isinstance(row, dict):
            continue
        if str(row.get("account_id") or "") != aid:
            continue
        row["type"] = account_type
        row["email"] = email or row.get("email") or login
        row["provider"] = provider
        imap = row.get("imap") if isinstance(row.get("imap"), dict) else {}
        if host:
            imap["host"] = host
        if port:
            imap["port"] = int(port)
        if login:
            imap["login"] = login
        if encryption:
            imap["encryption"] = encryption
        imap.pop("password", None)
        row["imap"] = imap
        found = True
        break
    if not found:
        accounts.append(
            {
                "account_id": aid,
                "type": account_type,
                "email": email or login,
                "provider": provider,
                "imap": {
                    "host": host,
                    "port": int(port or 993),
                    "encryption": encryption or "tls",
                    "login": login,
                },
            }
        )
    if password:
        vault.set_secret(aid, "password", password)
    cfg["accounts"] = accounts
    if make_default or not cfg.get("default_account_id"):
        cfg["default_account_id"] = aid if make_default else cfg.get("default_account_id") or aid
    # Keep legacy mailbox mirror for default account (password-less).
    if aid == (cfg.get("default_account_id") or DEFAULT_ACCOUNT_ID):
        row = next(r for r in accounts if isinstance(r, dict) and r.get("account_id") == aid)
        imap = row.get("imap") if isinstance(row.get("imap"), dict) else {}
        cfg["mailbox"] = {
            "email": row.get("email") or "",
            "imap": {
                "host": imap.get("host") or "",
                "port": int(imap.get("port") or 993),
                "encryption": imap.get("encryption") or "tls",
                "login": imap.get("login") or "",
            },
        }
    save_config(cfg)
    public = get_account(aid) or {"account_id": aid}
    return {"ok": True, "account": public}


def remove_account(account_id: str) -> dict[str, Any]:
    from . import vault

    aid = _safe_account_id(account_id)
    if aid == DEFAULT_ACCOUNT_ID:
        return {"ok": False, "error": "refusing to remove default account; clear credentials instead"}
    cfg = load_config()
    accounts = cfg.get("accounts")
    if not isinstance(accounts, list):
        return {"ok": False, "error": "account not found"}
    new_rows = [r for r in accounts if not (isinstance(r, dict) and r.get("account_id") == aid)]
    if len(new_rows) == len(accounts):
        return {"ok": False, "error": "account not found"}
    cfg["accounts"] = new_rows
    if cfg.get("default_account_id") == aid:
        cfg["default_account_id"] = DEFAULT_ACCOUNT_ID
    save_config(cfg)
    vault.delete_account_secrets(aid)
    return {"ok": True, "removed": aid}


def resolve_imap_config(account_id: str | None = None) -> dict[str, Any]:
    """Resolve IMAP config for an account. Env still wins for the default account."""
    from . import vault

    aid = (account_id or default_account_id()).strip() or DEFAULT_ACCOUNT_ID
    if aid == default_account_id() or account_id is None:
        env_cfg = imap_config_from_env()
        if env_cfg.get("host") and env_cfg.get("login"):
            return env_cfg

    cfg = load_config()
    accounts = cfg.get("accounts")
    if isinstance(accounts, list):
        for row in accounts:
            if not isinstance(row, dict) or str(row.get("account_id") or "") != aid:
                continue
            imap = row.get("imap") if isinstance(row.get("imap"), dict) else {}
            password = vault.get_secret(aid, "password") or str(imap.get("password") or "")
            return {
                "host": str(imap.get("host") or ""),
                "port": int(imap.get("port") or 993),
                "login": str(imap.get("login") or ""),
                "password": password,
                "encryption": str(imap.get("encryption") or "tls"),
                "account_id": aid,
            }

    if aid == DEFAULT_ACCOUNT_ID:
        file_cfg = imap_config_from_config()
        if file_cfg.get("host") and file_cfg.get("login"):
            if not file_cfg.get("password"):
                file_cfg["password"] = vault.get_secret(DEFAULT_ACCOUNT_ID, "password") or ""
            file_cfg["account_id"] = DEFAULT_ACCOUNT_ID
            return file_cfg
        env_cfg = imap_config_from_env()
        env_cfg["account_id"] = DEFAULT_ACCOUNT_ID
        return env_cfg

    return {"host": "", "port": 993, "login": "", "password": "", "encryption": "tls", "account_id": aid}

