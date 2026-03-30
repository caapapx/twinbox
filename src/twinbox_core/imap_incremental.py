"""Incremental IMAP sync helpers for Phase 1 daytime processing."""

from __future__ import annotations

import argparse
import imaplib
import json
import os
import re
import subprocess
from email.parser import BytesHeaderParser
from email.policy import default as email_policy
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable

from .artifacts import generated_at
from .imap_utf7 import mailbox_for_wire
from .merge_context import merge_incremental_context

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_FALLBACK = 20


def uid_watermarks_path(state_root: Path) -> Path:
    return state_root / "runtime" / "context" / "uid-watermarks.json"


def phase1_context_path(state_root: Path) -> Path:
    return state_root / "runtime" / "context" / "phase1-context.json"


def phase1_raw_dir(state_root: Path) -> Path:
    return state_root / "runtime" / "validation" / "phase-1" / "raw"


def load_uid_watermarks(state_root: Path) -> dict[str, Any]:
    path = uid_watermarks_path(state_root)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json_atomic(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def save_uid_watermarks(state_root: Path, payload: dict[str, Any]) -> Path:
    return _write_json_atomic(uid_watermarks_path(state_root), payload)


def _load_json_if_exists(path: Path, default: object) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


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


def _decode_imap_detail(parts: list[Any]) -> str:
    text = " ".join(
        part.decode(errors="ignore") if isinstance(part, bytes) else str(part)
        for part in parts
    ).strip()
    return text or "unknown IMAP error"


def _parse_flag_list(meta_text: str) -> list[str]:
    match = re.search(r"FLAGS\s+\((.*?)\)", meta_text)
    if not match:
        return []
    inner = match.group(1).strip()
    return [flag for flag in inner.split() if flag]


def _normalize_header_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return parsedate_to_datetime(text).isoformat()
    except (TypeError, ValueError):
        return text


def _decode_real_fetch_rows(fetch_data: list[Any], folder: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk in fetch_data:
        if not isinstance(chunk, tuple) or len(chunk) < 2:
            continue
        meta_raw, header_raw = chunk[0], chunk[1]
        meta_text = meta_raw.decode(errors="ignore") if isinstance(meta_raw, bytes) else str(meta_raw)
        uid_match = re.search(r"UID\s+(\d+)", meta_text)
        if uid_match is None:
            raise ValueError(f"FETCH response missing UID: {meta_text}")
        uid = int(uid_match.group(1))
        flags = _parse_flag_list(meta_text)
        header_bytes = header_raw if isinstance(header_raw, bytes) else str(header_raw).encode()
        message = BytesHeaderParser(policy=email_policy).parsebytes(header_bytes)
        from_name = ""
        from_addr = ""
        addresses = getaddresses([str(message.get("from", "") or "")])
        if addresses:
            from_name, from_addr = addresses[0]
        rows.append(
            {
                "id": str(uid),
                "uid": uid,
                "folder": folder,
                "subject": str(message.get("subject", "") or ""),
                "from_name": str(from_name or ""),
                "from_addr": str(from_addr or "").lower(),
                "date": _normalize_header_date(str(message.get("date", "") or "")),
                "message_id": str(message.get("message-id", "") or ""),
                "has_attachment": False,
                "flags": flags,
            }
        )
    return rows


def _decode_fetch_rows(fetch_data: list[Any], folder: str) -> list[dict[str, Any]]:
    if not fetch_data:
        return []

    first = fetch_data[0]
    if isinstance(first, (bytes, str)):
        raw = first.decode() if isinstance(first, bytes) else str(first)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            rows: list[dict[str, Any]] = []
            for row in payload:
                if not isinstance(row, dict):
                    continue
                envelope = row.get("envelope", {})
                if not isinstance(envelope, dict):
                    envelope = {}
                item = dict(envelope)
                item["folder"] = folder
                item["uid"] = int(row.get("uid", 0) or 0)
                item["flags"] = [str(flag) for flag in row.get("flags", [])]
                if not item.get("id") and item["uid"]:
                    item["id"] = str(item["uid"])
                rows.append(item)
            return rows

    return _decode_real_fetch_rows(fetch_data, folder)


def _build_imap_client(imap_config: dict[str, Any]):
    host = str(imap_config["host"])
    port = int(imap_config.get("port", 993))
    encryption = str(imap_config.get("encryption", "tls") or "tls").lower()
    if encryption in {"tls", "ssl"}:
        return imaplib.IMAP4_SSL(host, port)
    client = imaplib.IMAP4(host, port)
    if encryption == "starttls":
        client.starttls()
    return client


def fetch_incremental_envelopes(
    state_root: Path,
    folders: list[str],
    imap_config: dict[str, Any],
    watermarks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if watermarks is None:
        watermarks = load_uid_watermarks(state_root)

    client = _build_imap_client(imap_config)
    client.login(str(imap_config["login"]), str(imap_config["password"]))

    new_envelopes: list[dict[str, Any]] = []
    updated_watermarks = dict(watermarks)
    uidvalidity_changed: list[str] = []
    folder_errors: list[dict[str, str]] = []
    sync_time = generated_at()

    try:
        for folder in folders:
            wire = mailbox_for_wire(folder)
            status, select_data = client.select(wire, readonly=True)
            if status != "OK":
                folder_errors.append({"folder": folder, "step": "select", "detail": _decode_imap_detail(select_data)})
                continue

            current_uidvalidity = _parse_uidvalidity(select_data)
            previous = watermarks.get(folder, {}) if isinstance(watermarks.get(folder, {}), dict) else {}
            previous_uidvalidity = int(previous.get("uidvalidity", 0) or 0)
            previous_last_uid = int(previous.get("last_uid", 0) or 0)

            if previous_uidvalidity and previous_uidvalidity != current_uidvalidity:
                uidvalidity_changed.append(folder)
                updated_watermarks[folder] = {
                    "uidvalidity": current_uidvalidity,
                    "last_uid": 0,
                    "last_sync_at": sync_time,
                }
                continue

            search_start = previous_last_uid + 1
            status, search_data = client.uid("SEARCH", None, "UID", f"{search_start}:*")
            if status != "OK":
                folder_errors.append({"folder": folder, "step": "search", "detail": _decode_imap_detail(search_data)})
                continue

            uids = _decode_uid_list(search_data)
            fetched_rows: list[dict[str, Any]] = []
            if uids:
                status, fetch_data = client.uid(
                    "FETCH",
                    ",".join(str(uid) for uid in uids),
                    "(UID FLAGS BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE MESSAGE-ID)])",
                )
                if status != "OK":
                    folder_errors.append({"folder": folder, "step": "fetch", "detail": _decode_imap_detail(fetch_data)})
                    continue
                try:
                    fetched_rows = _decode_fetch_rows(fetch_data, folder)
                except Exception as exc:
                    folder_errors.append({"folder": folder, "step": "fetch_decode", "detail": str(exc)})
                    continue
                new_envelopes.extend(fetched_rows)

            updated_watermarks[folder] = {
                "uidvalidity": current_uidvalidity,
                "last_uid": max(uids) if uids else previous_last_uid,
                "last_sync_at": sync_time,
            }
    finally:
        client.logout()

    return {
        "new_envelopes": new_envelopes,
        "updated_watermarks": updated_watermarks,
        "uidvalidity_changed": uidvalidity_changed,
        "folder_errors": folder_errors,
    }


def _normalize_context_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(envelope.get("id", "") or ""),
        "folder": str(envelope.get("folder", "INBOX") or "INBOX"),
        "subject": str(envelope.get("subject", "") or ""),
        "from_name": str(envelope.get("from_name", "") or ""),
        "from_addr": str(envelope.get("from_addr", "") or "").lower(),
        "date": str(envelope.get("date", "") or ""),
        "has_attachment": bool(envelope.get("has_attachment", False)),
        "flags": [str(flag) for flag in envelope.get("flags", [])],
    }


def _sample_body_text(raw_output: str) -> str:
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        return ""
    return str(parsed or "")


def sample_incremental_bodies(
    envelopes: list[dict[str, Any]],
    *,
    himalaya_bin: str,
    config_path: Path,
    account: str,
    sample_body_count: int,
) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for envelope in envelopes[: max(0, sample_body_count)]:
        message_id = str(envelope.get("id", "") or "")
        folder = str(envelope.get("folder", "INBOX") or "INBOX")
        body = ""
        try:
            proc = subprocess.run(
                [
                    himalaya_bin,
                    "-c",
                    str(config_path),
                    "message",
                    "read",
                    "--preview",
                    "--account",
                    account,
                    "--folder",
                    folder,
                    message_id,
                    "--output",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                body = _sample_body_text(proc.stdout)[:3000]
        except OSError:
            body = ""
        out[message_id] = {
            "subject": str(envelope.get("subject", "") or ""),
            "body": body,
        }
    return out


def _load_existing_context(state_root: Path) -> dict[str, Any]:
    payload = _load_json_if_exists(phase1_context_path(state_root), {})
    return payload if isinstance(payload, dict) else {}


def _build_raw_body_rows(context_payload: dict[str, Any]) -> list[dict[str, Any]]:
    envelopes = context_payload.get("envelopes", [])
    body_map = context_payload.get("sampled_bodies", {})
    if not isinstance(envelopes, list) or not isinstance(body_map, dict):
        return []
    rows: list[dict[str, Any]] = []
    for envelope in envelopes:
        if not isinstance(envelope, dict):
            continue
        message_id = str(envelope.get("id", "") or "")
        body_row = body_map.get(message_id)
        if not isinstance(body_row, dict):
            continue
        rows.append(
            {
                "id": message_id,
                "folder": str(envelope.get("folder", "INBOX") or "INBOX"),
                "subject": str(body_row.get("subject", envelope.get("subject", "")) or ""),
                "body": str(body_row.get("body", "") or ""),
            }
        )
    return rows


def _write_phase1_outputs(
    state_root: Path,
    *,
    context_payload: dict[str, Any],
    folders: list[str],
) -> dict[str, str]:
    raw_root = phase1_raw_dir(state_root)
    context_file = _write_json_atomic(phase1_context_path(state_root), context_payload)
    envelopes_file = _write_json_atomic(raw_root / "envelopes-merged.json", context_payload.get("envelopes", []))
    bodies_file = _write_json_atomic(raw_root / "sample-bodies.json", _build_raw_body_rows(context_payload))
    folders_file = _write_json_atomic(raw_root / "folders.json", [{"name": folder} for folder in folders])
    return {
        "context_path": str(context_file),
        "raw_envelopes_path": str(envelopes_file),
        "raw_bodies_path": str(bodies_file),
        "folders_path": str(folders_file),
    }


def run_incremental_phase1(
    *,
    state_root: Path,
    folders: list[str],
    imap_config: dict[str, Any],
    account: str,
    config_path: Path,
    himalaya_bin: str,
    sample_body_count: int,
    lookback_days: int,
    owner_email: str,
    fetcher: Callable[..., dict[str, Any]] = fetch_incremental_envelopes,
    body_sampler: Callable[..., dict[str, dict[str, str]]] = sample_incremental_bodies,
    now: str | None = None,
) -> dict[str, Any]:
    existing_context = _load_existing_context(state_root)
    owner_domain = (str(owner_email or "").split("@", 1)[1] if "@" in str(owner_email or "") else "").lower()

    fetch_result = fetcher(
        state_root=state_root,
        folders=folders,
        imap_config=imap_config,
        watermarks=load_uid_watermarks(state_root),
    )
    folder_errors = fetch_result.get("folder_errors", [])
    if isinstance(folder_errors, list) and folder_errors:
        return {"status": "error", "folder_errors": folder_errors}

    uidvalidity_changed = fetch_result.get("uidvalidity_changed", [])
    if isinstance(uidvalidity_changed, list) and uidvalidity_changed:
        return {"status": "fallback_full", "uidvalidity_changed": uidvalidity_changed}

    new_envelopes = [
        _normalize_context_envelope(row)
        for row in fetch_result.get("new_envelopes", [])
        if isinstance(row, dict)
    ]
    updated_watermarks = fetch_result.get("updated_watermarks", {})
    if not isinstance(updated_watermarks, dict):
        updated_watermarks = {}

    if not new_envelopes:
        if not existing_context:
            return {"status": "fallback_full", "reason": "missing_context"}
        context_payload = {
            **existing_context,
            "generated_at": now or generated_at(),
            "owner_domain": owner_domain or str(existing_context.get("owner_domain", "") or ""),
            "lookback_days": int(existing_context.get("lookback_days", lookback_days) or lookback_days),
            "stats": {
                **(existing_context.get("stats", {}) if isinstance(existing_context.get("stats"), dict) else {}),
                "folders_scanned": [str(folder) for folder in folders],
            },
        }
        paths = _write_phase1_outputs(state_root, context_payload=context_payload, folders=folders)
        save_uid_watermarks(state_root, updated_watermarks)
        return {"status": "noop", **paths, "updated_watermarks": updated_watermarks}

    new_bodies = body_sampler(
        new_envelopes,
        himalaya_bin=himalaya_bin,
        config_path=config_path,
        account=account,
        sample_body_count=sample_body_count,
    )
    merged_context = merge_incremental_context(
        phase1_context_path(state_root),
        new_envelopes=new_envelopes,
        new_bodies=new_bodies,
        owner_domain=owner_domain,
        lookback_days=lookback_days,
        folders_scanned=folders,
        now=now,
    )
    paths = _write_phase1_outputs(state_root, context_payload=merged_context, folders=folders)
    save_uid_watermarks(state_root, updated_watermarks)
    return {
        "status": "incremental",
        **paths,
        "new_envelope_count": len(new_envelopes),
        "sampled_body_count": len(new_bodies),
        "updated_watermarks": updated_watermarks,
    }


def _load_folder_names(path: Path) -> list[str]:
    payload = _load_json_if_exists(path, [])
    if not isinstance(payload, list):
        return []
    folders: list[str] = []
    for row in payload:
        if isinstance(row, dict):
            name = str(row.get("name", "") or "")
        else:
            name = str(row or "")
        if name:
            folders.append(name)
    return folders


def _build_imap_config_from_env() -> dict[str, Any]:
    return {
        "host": str((os.environ.get("IMAP_HOST", "") or "")),
        "port": int(os.environ.get("IMAP_PORT", "993") or 993),
        "login": str((os.environ.get("IMAP_LOGIN", "") or "")),
        "password": str((os.environ.get("IMAP_PASS", "") or "")),
        "encryption": str((os.environ.get("IMAP_ENCRYPTION", "tls") or "tls")),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True, help="Twinbox state root")
    parser.add_argument("--folders-json", type=Path, required=True, help="Folder list JSON written by himalaya folder list")
    parser.add_argument("--account", required=True, help="MAIL_ACCOUNT_NAME")
    parser.add_argument("--config", type=Path, required=True, help="Himalaya config.toml path")
    parser.add_argument("--himalaya-bin", default="himalaya", help="Himalaya executable path")
    parser.add_argument("--sample-body-count", type=int, default=30, help="Number of new message bodies to sample")
    parser.add_argument("--lookback-days", type=int, default=7, help="Lookback window used for merged context")
    args = parser.parse_args(argv)

    folders = _load_folder_names(args.folders_json)
    result = run_incremental_phase1(
        state_root=args.state_root,
        folders=folders,
        imap_config=_build_imap_config_from_env(),
        account=args.account,
        config_path=args.config,
        himalaya_bin=args.himalaya_bin,
        sample_body_count=max(0, args.sample_body_count),
        lookback_days=max(1, args.lookback_days),
        owner_email=str((os.environ.get("MAIL_ADDRESS", "") or "")),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "fallback_full":
        return EXIT_FALLBACK
    if result.get("status") == "error":
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
