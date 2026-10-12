"""Human-confirmed outbound mail: local draft -> SMTP send -> Sent Items append.

Safety model (see AGENTS.md "Outbound mail"):
- ``create_draft`` never touches the network; it writes ``outbox/<draft_id>.eml``
  plus ``<draft_id>.json`` under the Twinbox state root and returns a preview and a
  single-use ``confirmation_token`` (only its sha256 is stored).
- ``send_draft`` refuses unless ``confirm`` is true, the token matches and is not
  expired, the draft exists and is not already sent, and outbound sending is
  enabled (``TWINBOX_SEND_ENABLED=1`` env or ``twinbox.json`` ``send.enabled``).
  Optional ``send.allowed_domains`` / ``TWINBOX_SEND_ALLOWED_DOMAINS`` restrict
  recipients.
- Credentials are read from the Himalaya config (auth raw/password or cmd) and are
  never returned, logged, or written.
"""

from __future__ import annotations

import hashlib
import hmac
import imaplib
import json
import os
import re
import secrets
import shlex
import smtplib
import ssl
import subprocess
import time
import tomllib
from email.message import EmailMessage
from email.utils import format_datetime, getaddresses, make_msgid, parsedate_to_datetime
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import load_config, state_root

SHANGHAI = ZoneInfo("Asia/Shanghai")
TOKEN_TTL_SECONDS = 30 * 60
DEFAULT_SENT_FOLDER = "Sent Items"
_DRAFT_ID_RE = re.compile(r"^d[0-9a-f]{20}$")


class SendError(Exception):
    """Carries a stable error code safe to cross the MCP boundary."""


# --- paths / config -------------------------------------------------------

def outbox_dir() -> Path:
    path = state_root() / "runtime" / "outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def himalaya_config_path() -> Path:
    raw = os.environ.get("TWINBOX_HIMALAYA_CONFIG", "").strip()
    if raw:
        return Path(raw).expanduser()
    return state_root() / "runtime" / "himalaya" / "config.toml"


def _send_settings() -> dict[str, Any]:
    cfg = load_config().get("send") or {}
    return cfg if isinstance(cfg, dict) else {}


def send_enabled() -> bool:
    env = os.environ.get("TWINBOX_SEND_ENABLED", "").strip().lower()
    if env:
        return env in {"1", "true", "yes", "on"}
    return bool(_send_settings().get("enabled", False))


def allowed_domains() -> list[str]:
    env = os.environ.get("TWINBOX_SEND_ALLOWED_DOMAINS", "").strip()
    if env:
        items = env.split(",")
    else:
        items = _send_settings().get("allowed_domains") or []
    return sorted({str(d).strip().lower().lstrip("@") for d in items if str(d).strip()})


def sent_folder() -> str:
    return str(os.environ.get("TWINBOX_SENT_FOLDER") or _send_settings().get("sent_folder") or DEFAULT_SENT_FOLDER)


# --- credentials ------------------------------------------------------------

def _resolve_secret(auth: dict[str, Any]) -> str:
    if auth.get("raw"):
        return str(auth["raw"])
    if auth.get("password") and isinstance(auth["password"], str):
        return auth["password"]
    if isinstance(auth.get("password"), dict):
        return _resolve_secret(auth["password"])
    cmd = auth.get("cmd") or auth.get("command")
    if cmd:
        argv = cmd if isinstance(cmd, list) else shlex.split(str(cmd))
        out = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
        if out.returncode != 0:
            raise SendError("credential_cmd_failed")
        return out.stdout.splitlines()[0].strip() if out.stdout else ""
    raise SendError("credential_missing")


def _dig(node: dict[str, Any], dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def load_mail_credentials(account_email: str | None = None) -> dict[str, Any]:
    """Return {email, display_name, smtp{}, imap{}} with secrets (internal use only)."""
    path = himalaya_config_path()
    if not path.exists():
        raise SendError("himalaya_config_missing")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    accounts = data.get("accounts") or {}
    chosen = None
    for acc in accounts.values():
        if account_email and str(acc.get("email", "")).lower() == account_email.lower():
            chosen = acc
            break
    if chosen is None:
        chosen = next((a for a in accounts.values() if a.get("default")), None) or next(iter(accounts.values()), None)
    if not chosen:
        raise SendError("himalaya_account_missing")

    def block(prefix: str) -> dict[str, Any]:
        b = _dig(chosen, prefix) or {}
        enc = _dig(b, "encryption.type") or b.get("encryption") or "tls"
        return {
            "host": b.get("host", ""),
            "port": int(b.get("port") or 0),
            "login": b.get("login") or chosen.get("email", ""),
            "encryption": str(enc).lower(),
            "auth": b.get("auth") or {},
        }

    smtp = block("message.send.backend")
    imap = block("backend")
    if not smtp["host"]:
        raise SendError("smtp_config_missing")
    return {
        "email": chosen.get("email", ""),
        "display_name": chosen.get("display-name", ""),
        "smtp": smtp,
        "imap": imap,
    }


# --- draft ------------------------------------------------------------------

def _split_addrs(values: list[str] | str | None) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    for _name, addr in getaddresses([v for v in values if v]):
        addr = addr.strip()
        if addr:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", addr):
                raise SendError("invalid_recipient")
            out.append(addr)
    return out


def _domain_violations(addrs: list[str]) -> list[str]:
    allowed = allowed_domains()
    if not allowed:
        return []
    return sorted({a for a in addrs if a.rsplit("@", 1)[-1].lower() not in allowed})


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _meta_path(draft_id: str) -> Path:
    return outbox_dir() / f"{draft_id}.json"


def _eml_path(draft_id: str) -> Path:
    return outbox_dir() / f"{draft_id}.eml"


def _write_meta(meta: dict[str, Any]) -> None:
    path = _meta_path(meta["draft_id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _excerpt(text: str, limit: int = 600) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _public(meta: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    keep = ("draft_id", "status", "message_id", "from_addr", "to", "cc", "bcc", "subject",
            "created_at", "sent_at", "eml_path", "body_excerpt", "has_html", "has_plain",
            "size_bytes", "token_expires_at", "smtp_accepted", "smtp_refused", "sent_items_verified")
    out = {k: meta[k] for k in keep if k in meta}
    if extra:
        out.update(extra)
    return out


def create_draft(
    *,
    to: list[str] | str,
    subject: str,
    plain: str = "",
    html: str = "",
    cc: list[str] | str | None = None,
    bcc: list[str] | str | None = None,
    from_name: str = "",
    sender: str = "",
) -> dict[str, Any]:
    to_l, cc_l, bcc_l = _split_addrs(to), _split_addrs(cc), _split_addrs(bcc)
    if not to_l:
        return {"ok": False, "error": "recipient_required"}
    if not (subject or "").strip():
        return {"ok": False, "error": "subject_required"}
    if not (plain or html):
        return {"ok": False, "error": "content_required"}
    bad = _domain_violations(to_l + cc_l + bcc_l)
    if bad:
        return {"ok": False, "error": "recipient_domain_not_allowed", "blocked_recipients": bad}

    from_addr = sender.strip()
    if not from_addr:
        try:
            from_addr = load_mail_credentials().get("email", "")
        except SendError:
            from_addr = ""
    if not from_addr:
        return {"ok": False, "error": "sender_unknown"}

    msg = EmailMessage()
    domain = from_addr.rsplit("@", 1)[-1]
    message_id = make_msgid(domain=domain)
    now = datetime.now(SHANGHAI)
    msg["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
    msg["To"] = ", ".join(to_l)
    if cc_l:
        msg["Cc"] = ", ".join(cc_l)
    msg["Subject"] = subject.strip()
    msg["Date"] = format_datetime(now)
    msg["Message-ID"] = message_id
    msg["MIME-Version"] = "1.0"
    if plain:
        msg.set_content(plain, charset="utf-8")
        if html:
            msg.add_alternative(html, subtype="html", charset="utf-8")
    else:
        msg.set_content(html, subtype="html", charset="utf-8")
    # Bcc is intentionally NOT a header: it is only an SMTP envelope recipient.
    raw = msg.as_bytes()

    draft_id = "d" + secrets.token_hex(10)
    token = secrets.token_urlsafe(16)
    eml = _eml_path(draft_id)
    eml.write_bytes(raw)
    os.chmod(eml, 0o600)
    meta = {
        "draft_id": draft_id,
        "status": "draft",
        "message_id": message_id,
        "from_addr": from_addr,
        "to": to_l,
        "cc": cc_l,
        "bcc": bcc_l,
        "subject": subject.strip(),
        "created_at": now.isoformat(),
        "eml_path": str(eml),
        "body_excerpt": _excerpt(plain or html),
        "has_plain": bool(plain),
        "has_html": bool(html),
        "size_bytes": len(raw),
        "token_sha256": _hash(token),
        "token_expires_at": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    _write_meta(meta)
    return {
        "ok": True,
        "data": _public(meta, {
            "confirmation_token": token,
            "send_enabled": send_enabled(),
            "next_step": "Show this preview to the human. Only after they explicitly approve in a later turn, "
                         "call twinbox_send with draft_id, confirm=true and confirmation_token.",
        }),
    }


def get_draft(draft_id: str) -> dict[str, Any]:
    if not _DRAFT_ID_RE.match(draft_id or ""):
        return {"ok": False, "error": "draft_not_found"}
    path = _meta_path(draft_id)
    if not path.exists():
        return {"ok": False, "error": "draft_not_found"}
    return {"ok": True, "data": _public(json.loads(path.read_text(encoding="utf-8")))}


# --- send -------------------------------------------------------------------

def _smtp_connect(smtp: dict[str, Any]):
    ctx = ssl.create_default_context()
    port = smtp["port"] or 465
    if smtp["encryption"] in ("starttls", "start-tls"):
        conn = smtplib.SMTP(smtp["host"], port, timeout=60)
        conn.starttls(context=ctx)
        return conn
    return smtplib.SMTP_SSL(smtp["host"], port, context=ctx, timeout=60)


def _imap_connect(imap: dict[str, Any]):
    return imaplib.IMAP4_SSL(imap["host"], imap["port"] or 993, ssl_context=ssl.create_default_context(), timeout=60)


def _mailbox_arg(name: str) -> str:
    from .imap_utf7 import mailbox_for_wire
    wire = mailbox_for_wire(name)
    return wire if wire.startswith('"') else f'"{wire}"'


def _imap_has_message_id(conn, folder: str, message_id: str) -> bool:
    typ, _ = conn.select(_mailbox_arg(folder))
    if typ != "OK":
        raise SendError("sent_folder_unavailable")
    typ, data = conn.search(None, "HEADER", "Message-ID", f'"{message_id}"')
    return typ == "OK" and bool(data and data[0] and data[0].split())


def append_to_sent(creds: dict[str, Any], raw: bytes, message_id: str, date_hdr: str) -> dict[str, Any]:
    imap = creds["imap"]
    folder = sent_folder()
    conn = _imap_connect(imap)
    try:
        conn.login(imap["login"], _resolve_secret(imap["auth"]))
        already = _imap_has_message_id(conn, folder, message_id)
        appended = False
        if not already:
            try:
                internal = imaplib.Time2Internaldate(parsedate_to_datetime(date_hdr).timestamp())
            except Exception:
                internal = imaplib.Time2Internaldate(time.time())
            typ, _ = conn.append(_mailbox_arg(folder), r"(\Seen)", internal, raw)
            if typ != "OK":
                raise SendError("sent_append_failed")
            appended = True
        verified = _imap_has_message_id(conn, folder, message_id)
        return {"sent_folder": folder, "appended": appended, "already_present": already, "verified": verified}
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def send_draft(draft_id: str, *, confirm: bool, confirmation_token: str) -> dict[str, Any]:
    if confirm is not True:
        return {"ok": False, "error": "confirmation_required"}
    if not _DRAFT_ID_RE.match(draft_id or "") or not _meta_path(draft_id).exists():
        return {"ok": False, "error": "draft_not_found"}
    meta = json.loads(_meta_path(draft_id).read_text(encoding="utf-8"))
    if meta.get("status") in ("sent", "sending"):
        return {"ok": False, "error": "draft_already_sent", "data": _public(meta)}
    if not confirmation_token or not hmac.compare_digest(_hash(confirmation_token), meta.get("token_sha256", "")):
        return {"ok": False, "error": "confirmation_token_invalid"}
    if int(time.time()) > int(meta.get("token_expires_at", 0)):
        return {"ok": False, "error": "confirmation_token_expired"}
    if not send_enabled():
        return {"ok": False, "error": "send_disabled", "recovery": "set TWINBOX_SEND_ENABLED=1 or twinbox.json send.enabled=true"}
    recipients = meta["to"] + meta.get("cc", []) + meta.get("bcc", [])
    bad = _domain_violations(recipients)
    if bad:
        return {"ok": False, "error": "recipient_domain_not_allowed", "blocked_recipients": bad}
    raw = Path(meta["eml_path"]).read_bytes()

    creds = load_mail_credentials(meta.get("from_addr"))
    # Mark before network I/O so a crash/retry cannot double-send.
    meta["status"] = "sending"
    meta.pop("token_sha256", None)
    _write_meta(meta)
    smtp = creds["smtp"]
    try:
        conn = _smtp_connect(smtp)
        try:
            conn.login(smtp["login"], _resolve_secret(smtp["auth"]))
            refused = conn.sendmail(meta["from_addr"], recipients, raw) or {}
        finally:
            try:
                conn.quit()
            except Exception:
                pass
    except smtplib.SMTPRecipientsRefused as exc:
        meta["status"] = "failed"
        meta["smtp_refused"] = sorted(exc.recipients)
        _write_meta(meta)
        return {"ok": False, "error": "smtp_all_recipients_refused", "data": _public(meta)}
    except (smtplib.SMTPException, OSError, SendError) as exc:
        meta["status"] = "failed_unknown"
        _write_meta(meta)
        code = str(exc) if isinstance(exc, SendError) else "smtp_error:" + type(exc).__name__
        return {"ok": False, "error": code, "data": _public(meta)}

    meta["status"] = "sent"
    meta["sent_at"] = datetime.now(SHANGHAI).isoformat()
    meta["smtp_refused"] = sorted(refused.keys())
    meta["smtp_accepted"] = [r for r in recipients if r not in refused]
    _write_meta(meta)

    date_hdr = ""
    for line in raw.split(b"\r\n\r\n", 1)[0].replace(b"\r\n", b"\n").split(b"\n"):
        if line.lower().startswith(b"date:"):
            date_hdr = line[5:].decode().strip()
    sent_info: dict[str, Any]
    try:
        sent_info = append_to_sent(creds, raw, meta["message_id"], date_hdr)
    except (imaplib.IMAP4.error, OSError, SendError) as exc:
        sent_info = {"verified": False, "sent_append_error": str(exc) if isinstance(exc, SendError) else type(exc).__name__}
    meta["sent_items_verified"] = bool(sent_info.get("verified"))
    _write_meta(meta)
    return {"ok": True, "data": _public(meta, {"sent_items": sent_info})}
