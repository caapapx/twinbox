"""Local Fernet credential vault (credentials encrypted at rest)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .config import state_root

VAULT_FILENAME = "vault.enc"
VAULT_KEY_FILENAME = ".vault_key"


def vault_path(root: Path | None = None) -> Path:
    return (root or state_root()) / VAULT_FILENAME


def vault_key_path(root: Path | None = None) -> Path:
    return (root or state_root()) / VAULT_KEY_FILENAME


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _load_or_create_fernet(root: Path | None = None) -> Fernet:
    key_file = vault_key_path(root)
    if key_file.is_file():
        key = key_file.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(key + b"\n")
        _chmod_private(key_file)
    return Fernet(key)


def _read_payload(root: Path | None = None) -> dict[str, Any]:
    path = vault_path(root)
    if not path.is_file():
        return {"version": 1, "secrets": {}}
    fernet = _load_or_create_fernet(root)
    try:
        raw = fernet.decrypt(path.read_bytes())
    except InvalidToken as exc:
        raise RuntimeError("vault decrypt failed; check .vault_key") from exc
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        return {"version": 1, "secrets": {}}
    secrets = payload.get("secrets")
    if not isinstance(secrets, dict):
        payload["secrets"] = {}
    payload.setdefault("version", 1)
    return payload


def _write_payload(payload: dict[str, Any], root: Path | None = None) -> None:
    path = vault_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fernet = _load_or_create_fernet(root)
    blob = fernet.encrypt(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    path.write_bytes(blob)
    _chmod_private(path)


def set_secret(account_id: str, field: str, value: str, *, root: Path | None = None) -> None:
    aid = (account_id or "").strip()
    if not aid:
        raise ValueError("account_id required")
    field = (field or "").strip()
    if not field:
        raise ValueError("field required")
    payload = _read_payload(root)
    secrets = payload.setdefault("secrets", {})
    entry = secrets.get(aid)
    if not isinstance(entry, dict):
        entry = {}
        secrets[aid] = entry
    entry[field] = value
    _write_payload(payload, root)


def get_secret(account_id: str, field: str, *, root: Path | None = None) -> str | None:
    aid = (account_id or "").strip()
    field = (field or "").strip()
    if not aid or not field:
        return None
    payload = _read_payload(root)
    entry = payload.get("secrets", {}).get(aid)
    if not isinstance(entry, dict):
        return None
    value = entry.get(field)
    return str(value) if value is not None else None


def has_secret(account_id: str, field: str = "password", *, root: Path | None = None) -> bool:
    value = get_secret(account_id, field, root=root)
    return bool(value)


def delete_account_secrets(account_id: str, *, root: Path | None = None) -> bool:
    aid = (account_id or "").strip()
    if not aid:
        return False
    payload = _read_payload(root)
    secrets = payload.get("secrets", {})
    if aid not in secrets:
        return False
    del secrets[aid]
    _write_payload(payload, root)
    return True


def public_secret_flags(account_id: str, *, root: Path | None = None) -> dict[str, bool]:
    """Presence booleans only — never return secret values."""
    return {"password_set": has_secret(account_id, "password", root=root)}
