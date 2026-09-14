"""IMAP fetch — pure imaplib, no himalaya binary dependency.

Provides incremental envelope fetching with UID watermarks,
and body text sampling via IMAP FETCH.
"""

from __future__ import annotations

import imaplib
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from email import message_from_bytes
from email.header import decode_header
from email.parser import BytesHeaderParser
from email.policy import default as email_policy
from email.utils import getaddresses, parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .imap_utf7 import mailbox_for_wire
from .recipient import apply_envelope_role

SHANGHAI = ZoneInfo("Asia/Shanghai")
IMAP_TIMEOUT_SEC = int(os.environ.get("TWINBOX_IMAP_TIMEOUT", "90") or "90")
HEADER_FIELDS = "SUBJECT FROM DATE MESSAGE-ID TO CC LIST-ID IN-REPLY-TO REFERENCES"
MAX_THREAD_CANDIDATES = 45
MAX_BODY_FETCH = 24
BODY_FETCH_SPEC = "(BODY.PEEK[])"
BODY_FETCH_CHUNK_SIZE = 20


def _now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def _load_json(path: Path, default: object) -> object:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


# --- Paths ---

def _watermarks_path(state_root: Path) -> Path:
    return state_root / "runtime" / "context" / "uid-watermarks.json"


def _context_path(state_root: Path) -> Path:
    return state_root / "runtime" / "context" / "phase1-context.json"


def _raw_dir(state_root: Path) -> Path:
    return state_root / "runtime" / "validation" / "phase-1" / "raw"


# --- IMAP helpers ---

def _apply_imap_timeout(client: imaplib.IMAP4 | imaplib.IMAP4_SSL) -> None:
    sock = getattr(client, "sock", None) or getattr(client, "socket", None)
    if sock is not None:
        sock.settimeout(IMAP_TIMEOUT_SEC)


def _build_client(imap_config: dict[str, Any]):
    host = str(imap_config["host"])
    port = int(imap_config.get("port", 993))
    encryption = str(imap_config.get("encryption", "tls") or "tls").lower()
    if encryption in {"tls", "ssl"}:
        client = imaplib.IMAP4_SSL(host, port)
    else:
        client = imaplib.IMAP4(host, port)
        if encryption == "starttls":
            client.starttls()
    _apply_imap_timeout(client)
    return client


def _parse_uidvalidity(select_data: list[bytes]) -> int:
    text = " ".join(
        chunk.decode(errors="ignore") if isinstance(chunk, bytes) else str(chunk)
        for chunk in select_data
    )
    match = re.search(r"UIDVALIDITY\s+(\d+)", text)
    return int(match.group(1)) if match else 0


def _decode_uid_list(search_data: list[bytes]) -> list[int]:
    if not search_data:
        return []
    raw = search_data[0].decode() if isinstance(search_data[0], bytes) else str(search_data[0])
    return [int(part) for part in raw.split() if part.isdigit()]


def _normalize_header_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return parsedate_to_datetime(text).isoformat()
    except (TypeError, ValueError):
        return text


def _decode_header_value(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    parts: list[str] = []
    try:
        for chunk, charset in decode_header(text):
            if isinstance(chunk, bytes):
                decoded, _enc = _decode_charset(chunk, charset)
                parts.append(decoded)
            else:
                parts.append(str(chunk))
    except (LookupError, UnicodeDecodeError, ValueError):
        return text
    return "".join(parts).strip()


def _decode_charset(raw: bytes, charset: str | None) -> tuple[str, str]:
    candidates: list[str] = []
    if charset:
        candidates.append(str(charset))
    candidates.extend(["utf-8", "gb18030", "gb2312", "big5", "latin-1"])
    seen: set[str] = set()
    for enc in candidates:
        key = enc.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            return raw.decode(key), key
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8/replace"


def _html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def decode_message_bytes(raw: bytes, *, max_chars: int = 0) -> dict[str, Any]:
    """Decode RFC822 bytes to UTF-8 plain text + attachment metadata."""
    if not raw:
        return {
            "body_text": "",
            "charset": "",
            "decoded_with": "",
            "attachments": [],
            "truncated": False,
        }
    msg = message_from_bytes(raw, policy=email_policy)
    texts: list[str] = []
    html_bits: list[str] = []
    attachments: list[dict[str, Any]] = []
    decoded_with = ""

    def walk(part) -> None:
        nonlocal decoded_with
        ctype = (part.get_content_type() or "").lower()
        disp = str(part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        if filename:
            filename = _decode_header_value(filename)
        if disp == "attachment" or (filename and ctype not in {"text/plain", "text/html"}):
            attachments.append({
                "filename": filename or "unnamed",
                "content_type": ctype or "application/octet-stream",
                "size": len(part.get_payload(decode=True) or b""),
            })
            return
        if ctype.startswith("image/") or ctype.startswith("application/"):
            attachments.append({
                "filename": filename or "inline",
                "content_type": ctype,
                "size": len(part.get_payload(decode=True) or b""),
            })
            return
        if part.is_multipart():
            for child in part.iter_parts():
                walk(child)
            return
        if ctype not in {"text/plain", "text/html"}:
            return
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            payload = str(payload or "").encode("utf-8", errors="replace")
        text, enc = _decode_charset(payload, part.get_content_charset())
        decoded_with = decoded_with or enc
        if ctype == "text/html":
            html_bits.append(_html_to_text(text))
        else:
            texts.append(text)

    walk(msg)
    body = "\n".join(t for t in texts if t.strip()) or "\n".join(h for h in html_bits if h.strip())
    truncated = False
    if max_chars and max_chars > 0 and len(body) > max_chars:
        body = body[:max_chars]
        truncated = True
    return {
        "body_text": body,
        "charset": decoded_with,
        "decoded_with": decoded_with,
        "attachments": attachments,
        "truncated": truncated,
    }


def _parse_flag_list(meta_text: str) -> list[str]:
    match = re.search(r"FLAGS\s+\((.*?)\)", meta_text)
    if not match:
        return []
    return [flag for flag in match.group(1).strip().split() if flag]


def _decode_fetch_rows(fetch_data: list[Any], folder: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk in fetch_data:
        if not isinstance(chunk, tuple) or len(chunk) < 2:
            continue
        meta_raw, header_raw = chunk[0], chunk[1]
        meta_text = meta_raw.decode(errors="ignore") if isinstance(meta_raw, bytes) else str(meta_raw)
        uid_match = re.search(r"UID\s+(\d+)", meta_text)
        if uid_match is None:
            continue
        uid = int(uid_match.group(1))
        flags = _parse_flag_list(meta_text)
        header_bytes = header_raw if isinstance(header_raw, bytes) else str(header_raw).encode()
        msg = BytesHeaderParser(policy=email_policy).parsebytes(header_bytes)
        from_name, from_addr = "", ""
        addresses = getaddresses([str(msg.get("from", "") or "")])
        if addresses:
            from_name, from_addr = addresses[0]
        to_raw = str(msg.get("to", "") or "")
        cc_raw = str(msg.get("cc", "") or "")
        rows.append({
            "id": str(uid),
            "uid": uid,
            "folder": folder,
            "subject": _decode_header_value(msg.get("subject", "") or ""),
            "from_name": str(from_name or ""),
            "from_addr": str(from_addr or "").lower(),
            "date": _normalize_header_date(str(msg.get("date", "") or "")),
            "message_id": str(msg.get("message-id", "") or ""),
            "to": to_raw,
            "cc": cc_raw,
            "list_id": str(msg.get("list-id", "") or ""),
            "in_reply_to": str(msg.get("in-reply-to", "") or ""),
            "references": str(msg.get("references", "") or ""),
            "has_attachment": False,
            "flags": flags,
        })
    return rows


# --- Body fetch ---

def _imap_date(value: date) -> str:
    """Format date for IMAP SEARCH (dd-Mon-yyyy)."""
    return value.strftime("%d-%b-%Y")


def fetch_bodies_imap(
    envelopes: list[dict[str, Any]],
    imap_config: dict[str, Any],
    *,
    max_chars: int = 500_000,
    client: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None,
) -> dict[str, str]:
    """Fetch body text for envelopes; key is uid within folder (folder#uid)."""
    if not envelopes:
        return {}

    own_client = client is None
    if own_client:
        client = _build_client(imap_config)
        client.login(str(imap_config["login"]), str(imap_config["password"]))

    out: dict[str, str] = {}
    try:
        by_folder: dict[str, list[dict[str, Any]]] = {}
        for env in envelopes:
            folder = str(env.get("folder", "INBOX") or "INBOX")
            if str(env.get("id", "") or ""):
                by_folder.setdefault(folder, []).append(env)

        for folder, folder_envs in by_folder.items():
            wire = mailbox_for_wire(folder)
            status, _ = client.select(wire, readonly=True)
            if status != "OK":
                continue
            by_uid = {str(env["id"]): env for env in folder_envs}
            uids = list(by_uid)
            for i in range(0, len(uids), BODY_FETCH_CHUNK_SIZE):
                uid_set = ",".join(uids[i : i + BODY_FETCH_CHUNK_SIZE])
                try:
                    status, data = client.uid("FETCH", uid_set, BODY_FETCH_SPEC)
                    if status != "OK" or not data:
                        continue
                    for part in data:
                        if not (isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], bytes)):
                            continue
                        meta_raw, raw = part[0], part[1]
                        meta_text = meta_raw.decode(errors="ignore") if isinstance(meta_raw, bytes) else str(meta_raw)
                        uid_match = re.search(r"UID\s+(\d+)", meta_text)
                        if uid_match is None:
                            continue
                        uid = uid_match.group(1)
                        env = by_uid.get(uid)
                        if env is None:
                            continue
                        decoded = decode_message_bytes(raw, max_chars=max_chars)
                        out[f"{folder}#{uid}"] = decoded["body_text"]
                        env["attachments"] = decoded.get("attachments", [])
                        env["decoded_with"] = decoded.get("decoded_with", "")
                        env["body_truncated"] = decoded.get("truncated", False)
                except Exception:
                    continue
    finally:
        if own_client:
            try:
                client.logout()
            except Exception:
                pass

    return out


def _structure_score(env: dict[str, Any]) -> int:
    score = 0
    flags = [str(f) for f in env.get("flags", [])]
    if "Seen" not in flags:
        score += 20
    role = str(env.get("recipient_role", "") or "")
    if role in {"to", "direct"}:
        score += 30
    elif role in {"cc", "cc_only"}:
        score += 10
    date_str = str(env.get("date", "") or "")
    if date_str:
        score += min(len(date_str), 20)
    return score


def rank_thread_candidates(
    envelopes: list[dict[str, Any]],
    *,
    max_threads: int = MAX_THREAD_CANDIDATES,
) -> list[dict[str, Any]]:
    from .pulse import normalize_thread_key

    grouped: dict[str, list[dict[str, Any]]] = {}
    for env in envelopes:
        tk = normalize_thread_key(env.get("subject"))
        grouped.setdefault(tk, []).append(env)
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for tk, rows in grouped.items():
        rows_sorted = sorted(rows, key=lambda r: str(r.get("date", "")), reverse=True)
        latest = rows_sorted[0]
        score = max(_structure_score(r) for r in rows_sorted)
        ranked.append((score, str(latest.get("date", "")), latest))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked[:max_threads]]


def sample_bodies_imap(
    envelopes: list[dict[str, Any]],
    imap_config: dict[str, Any],
    sample_count: int = MAX_BODY_FETCH,
    *,
    client: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None,
) -> dict[str, dict[str, str]]:
    """Two-stage sample: rank candidate threads, then fetch bodies for top N."""
    if not envelopes or sample_count <= 0:
        return {}
    candidates = rank_thread_candidates(envelopes, max_threads=MAX_THREAD_CANDIDATES)
    fetch_list = candidates[: min(sample_count, MAX_BODY_FETCH)]
    bodies = fetch_bodies_imap(fetch_list, imap_config, max_chars=8000, client=client)
    out: dict[str, dict[str, str]] = {}
    for env in fetch_list:
        uid = str(env.get("id", "") or "")
        folder = str(env.get("folder", "INBOX") or "INBOX")
        key = f"{folder}#{uid}"
        if key in bodies:
            out[key] = {
                "subject": str(env.get("subject", "") or ""),
                "body": bodies[key],
                "decoded_with": str(env.get("decoded_with", "") or ""),
                "attachments": env.get("attachments") or [],
            }
            out[uid] = out[key]
    return out


def _imap_search_uids(
    client: imaplib.IMAP4 | imaplib.IMAP4_SSL,
    *,
    since: date,
    until: date | None,
    subject_term: str | None = None,
) -> list[int]:
    """Run UID SEARCH for date window, optionally narrowing by Subject header."""
    criteria: list[str] = ["SINCE", _imap_date(since)]
    if until is not None:
        criteria.extend(["BEFORE", _imap_date(until)])
    if subject_term:
        criteria.extend(["HEADER", "Subject", subject_term])

    # Prefer UTF-8 for CJK subject terms; fall back to default charset.
    for charset in ("UTF-8", None):
        try:
            if charset:
                status, search_data = client.uid("SEARCH", charset, *criteria)
            else:
                status, search_data = client.uid("SEARCH", None, *criteria)
        except Exception:
            continue
        if status == "OK":
            return _decode_uid_list(search_data)
    return []


def _fetch_envelope_headers(
    client: imaplib.IMAP4 | imaplib.IMAP4_SSL,
    folder: str,
    uids: list[int],
    *,
    chunk_size: int = 80,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(0, len(uids), chunk_size):
        chunk = uids[i : i + chunk_size]
        uid_set = ",".join(str(u) for u in chunk)
        status, fetch_data = client.uid(
            "FETCH",
            uid_set,
            "(UID FLAGS BODY.PEEK[HEADER.FIELDS (" + HEADER_FIELDS + ")])",
        )
        if status != "OK":
            continue
        try:
            rows.extend(_decode_fetch_rows(fetch_data, folder))
        except Exception:
            continue
    return rows


def _normalize_envelope_row(row: dict[str, Any], owner_addr: str = "") -> dict[str, Any]:
    env = {
        "id": str(row.get("id", "") or ""),
        "folder": str(row.get("folder", "INBOX") or "INBOX"),
        "subject": str(row.get("subject", "") or ""),
        "from_name": str(row.get("from_name", "") or ""),
        "from_addr": str(row.get("from_addr", "") or "").lower(),
        "date": str(row.get("date", "") or ""),
        "message_id": str(row.get("message_id", "") or ""),
        "to": str(row.get("to", "") or ""),
        "cc": str(row.get("cc", "") or ""),
        "list_id": str(row.get("list_id", "") or ""),
        "in_reply_to": str(row.get("in_reply_to", "") or ""),
        "references": str(row.get("references", "") or ""),
        "has_attachment": bool(row.get("has_attachment", False)),
        "flags": [str(f) for f in row.get("flags", [])],
        "body": str(row.get("body", "") or ""),
    }
    return apply_envelope_role(env, owner_addr)


def fetch_by_query(
    imap_config: dict[str, Any],
    folders: list[str],
    *,
    since: date,
    until: date | None = None,
    fetch_bodies: bool = True,
    subject_terms: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Fetch envelopes in date range across folders; does not touch sync state.

    When subject_terms is set, IMAP HEADER Subject searches are unioned first to
    avoid fetching every message in the window (important for multi-month ranges).
    Client-side regex/body filters still apply after headers are retrieved.
    """
    if not folders:
        return [], [{"detail": "no folders specified"}]

    client = _build_client(imap_config)
    client.login(str(imap_config["login"]), str(imap_config["password"]))

    envelopes: list[dict[str, Any]] = []
    folder_errors: list[dict[str, str]] = []

    try:
        for folder in folders:
            wire = mailbox_for_wire(folder)
            status, _ = client.select(wire, readonly=True)
            if status != "OK":
                folder_errors.append({"folder": folder, "step": "select", "detail": "SELECT failed"})
                continue

            criteria = ["SINCE", _imap_date(since)]
            if until is not None:
                criteria.extend(["BEFORE", _imap_date(until)])

            uids: list[int] = []
            terms = [t.strip() for t in (subject_terms or []) if t and t.strip()]
            if terms:
                uid_set: set[int] = set()
                for term in terms:
                    uid_set.update(_imap_search_uids(client, since=since, until=until, subject_term=term))
                uids = sorted(uid_set)
            else:
                status, search_data = client.uid("SEARCH", None, *criteria)
                if status != "OK":
                    folder_errors.append({"folder": folder, "step": "search", "detail": "SEARCH failed"})
                    continue
                uids = _decode_uid_list(search_data)

            if not uids:
                continue

            try:
                envelopes.extend(_fetch_envelope_headers(client, folder, uids))
            except Exception as exc:
                folder_errors.append({"folder": folder, "step": "fetch", "detail": str(exc)})

        if folder_errors and not envelopes:
            return [], folder_errors

        from .config import owner_email

        owner_addr = owner_email()
        normalized: list[dict[str, Any]] = [_normalize_envelope_row(row, owner_addr) for row in envelopes]

        if fetch_bodies and normalized:
            bodies = fetch_bodies_imap(normalized, imap_config, client=client)
            for row in normalized:
                key = f"{row['folder']}#{row['id']}"
                row["body"] = bodies.get(key, "")

        normalized.sort(key=lambda r: str(r.get("date", "")), reverse=True)
        return normalized, folder_errors
    finally:
        try:
            client.logout()
        except Exception:
            pass


# --- Incremental fetch ---

def fetch_incremental(
    state_root: Path,
    folders: list[str],
    imap_config: dict[str, Any],
    *,
    sample_body_count: int = 30,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """Fetch new envelopes + bodies incrementally, merge with existing context."""
    watermarks_path = _watermarks_path(state_root)
    watermarks = _load_json(watermarks_path, {})
    if not isinstance(watermarks, dict):
        watermarks = {}

    started = time.monotonic()
    client = _build_client(imap_config)
    client.login(str(imap_config["login"]), str(imap_config["password"]))

    new_envelopes: list[dict[str, Any]] = []
    updated_watermarks = dict(watermarks)
    folder_errors: list[dict[str, str]] = []
    sync_time = _now_iso()

    try:
        for folder in folders:
            wire = mailbox_for_wire(folder)
            status, select_data = client.select(wire, readonly=True)
            if status != "OK":
                folder_errors.append({"folder": folder, "step": "select", "detail": "SELECT failed"})
                continue

            current_uv = _parse_uidvalidity(select_data)
            prev = watermarks.get(folder, {}) if isinstance(watermarks.get(folder), dict) else {}
            prev_uv = int(prev.get("uidvalidity", 0) or 0)
            prev_uid = int(prev.get("last_uid", 0) or 0)

            if prev_uv and prev_uv != current_uv:
                updated_watermarks[folder] = {"uidvalidity": current_uv, "last_uid": 0, "last_sync_at": sync_time}
                continue

            search_start = prev_uid + 1
            status, search_data = client.uid("SEARCH", None, "UID", f"{search_start}:*")
            if status != "OK":
                folder_errors.append({"folder": folder, "step": "search", "detail": "SEARCH failed"})
                continue

            uids = _decode_uid_list(search_data)
            if uids:
                uid_set = ",".join(str(u) for u in uids)
                status, fetch_data = client.uid(
                    "FETCH", uid_set,
                    "(UID FLAGS BODY.PEEK[HEADER.FIELDS (" + HEADER_FIELDS + ")])",
                )
                if status == "OK":
                    try:
                        new_envelopes.extend(_decode_fetch_rows(fetch_data, folder))
                    except Exception as exc:
                        folder_errors.append({"folder": folder, "step": "decode", "detail": str(exc)})
                        continue

            updated_watermarks[folder] = {
                "uidvalidity": current_uv,
                "last_uid": max(uids) if uids else prev_uid,
                "last_sync_at": sync_time,
            }
    except Exception:
        try:
            client.logout()
        except Exception:
            pass
        raise

    if folder_errors:
        try:
            client.logout()
        except Exception:
            pass
        return {"status": "error", "folder_errors": folder_errors}

    imap_envelope_ms = round((time.monotonic() - started) * 1000)

    # Merge with existing context
    from .config import owner_email

    owner = owner_email().strip()
    owner_domain = (owner.split("@", 1)[1] if "@" in owner else "").lower()

    existing_path = _context_path(state_root)
    existing = _load_json(existing_path, {})
    if not isinstance(existing, dict):
        existing = {}

    # Normalize new envelopes
    normalized = [_normalize_envelope_row(row, owner) for row in new_envelopes]

    # Merge envelopes by (id, folder)
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in (existing.get("envelopes", []) if isinstance(existing.get("envelopes"), list) else []):
        if isinstance(row, dict):
            merged[(str(row.get("id", "")), str(row.get("folder", "")))] = row
    for row in normalized:
        merged[(row["id"], row["folder"])] = row

    # Trim to lookback window
    cutoff = datetime.now(SHANGHAI) - timedelta(days=lookback_days)
    all_envs = list(merged.values())
    filtered = []
    for row in all_envs:
        date_str = str(row.get("date", "") or "")
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=SHANGHAI)
            if dt >= cutoff:
                filtered.append(row)
        except ValueError:
            filtered.append(row)  # keep if unparseable
    filtered.sort(key=lambda r: str(r.get("date", "")), reverse=True)

    # Sample bodies for new envelopes
    body_started = time.monotonic()
    new_bodies: dict[str, dict[str, str]] = {}
    if normalized:
        try:
            new_bodies = sample_bodies_imap(normalized, imap_config, sample_body_count, client=client)
        except Exception:
            pass  # non-fatal
    try:
        client.logout()
    except Exception:
        pass
    imap_body_ms = round((time.monotonic() - body_started) * 1000)

    # Merge body map
    body_map = existing.get("sampled_bodies", {}) if isinstance(existing.get("sampled_bodies"), dict) else {}
    active_ids = {str(r.get("id", "")) for r in filtered}
    body_map = {k: v for k, v in body_map.items() if k in active_ids}
    body_map.update(new_bodies)

    embedding_started = time.monotonic()
    embeddings_degraded = False
    try:
        from .embeddings import embed_new_messages
        embed_new_messages(state_root, filtered, body_map)
    except Exception:
        embeddings_degraded = True
    embed_ms = round((time.monotonic() - embedding_started) * 1000)

    context = {
        "generated_at": sync_time,
        "owner_domain": owner_domain,
        "lookback_days": lookback_days,
        "envelopes": filtered,
        "sampled_bodies": body_map,
        "stats": {
            "total_envelopes": len(filtered),
            "sampled_bodies": len(body_map),
            "folders_scanned": folders,
            "embeddings_degraded": embeddings_degraded,
        },
    }

    # Write outputs
    pulse_started = time.monotonic()
    _write_json(_context_path(state_root), context)
    _write_json(_raw_dir(state_root) / "envelopes-merged.json", filtered)
    _write_json(watermarks_path, updated_watermarks)
    pulse_ms = round((time.monotonic() - pulse_started) * 1000)

    return {
        "status": "ok" if normalized else "noop",
        "new_envelope_count": len(normalized),
        "sampled_body_count": len(new_bodies),
        "total_envelopes": len(filtered),
        "embeddings_degraded": embeddings_degraded,
        "timings_ms": {
            "imap_envelope_ms": imap_envelope_ms,
            "imap_body_ms": imap_body_ms,
            "embed_ms": embed_ms,
            "pulse_ms": pulse_ms,
        },
    }


def preflight(imap_config: dict[str, Any]) -> dict[str, Any]:
    """Quick IMAP connectivity test."""
    if not imap_config.get("host"):
        return {"ok": False, "error": "IMAP_HOST not set"}
    if not imap_config.get("login"):
        return {"ok": False, "error": "IMAP_LOGIN not set"}
    if not imap_config.get("password"):
        return {"ok": False, "error": "IMAP_PASS not set"}
    try:
        client = _build_client(imap_config)
        client.login(str(imap_config["login"]), str(imap_config["password"]))
        status, data = client.select(mailbox_for_wire("INBOX"), readonly=True)
        client.logout()
        if status == "OK":
            return {"ok": True, "status": "mailbox-connected"}
        return {"ok": False, "error": f"SELECT INBOX failed: {status}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
