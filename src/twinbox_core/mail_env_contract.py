"""Mailbox ↔ OpenClaw .env key sets.

Keep in sync with ``SKILL.md`` ``metadata.openclaw`` (requires.env, optionalDefaults keys).
"""

from __future__ import annotations

from typing import Mapping

# IMAP + SMTP block only (preflight JSON field ``required_env``).
OPENCLAW_IMAP_SMTP_ENV_KEYS: tuple[str, ...] = (
    "IMAP_HOST",
    "IMAP_PORT",
    "IMAP_LOGIN",
    "IMAP_PASS",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_LOGIN",
    "SMTP_PASS",
)

# Password-env runtime + OpenClaw strict requires (includes ``MAIL_ADDRESS``).
OPENCLAW_REQUIRES_ENV_KEYS: tuple[str, ...] = OPENCLAW_IMAP_SMTP_ENV_KEYS + ("MAIL_ADDRESS",)

OPENCLAW_OPTIONAL_MAIL_KEYS: tuple[str, ...] = (
    "MAIL_ACCOUNT_NAME",
    "MAIL_DISPLAY_NAME",
    "IMAP_ENCRYPTION",
    "SMTP_ENCRYPTION",
)

# Keys merged into openclaw.json skill env when ``sync_env_from_dotenv``.
OPENCLAW_ENV_KEYS: tuple[str, ...] = OPENCLAW_REQUIRES_ENV_KEYS + OPENCLAW_OPTIONAL_MAIL_KEYS


def missing_required_mail_values(data: Mapping[str, str]) -> list[str]:
    """Return keys from :data:`OPENCLAW_REQUIRES_ENV_KEYS` that are missing or blank."""
    return [k for k in OPENCLAW_REQUIRES_ENV_KEYS if not str(data.get(k, "") or "").strip()]
