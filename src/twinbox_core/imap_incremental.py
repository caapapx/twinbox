"""Incremental IMAP sync helpers for Phase 1 daytime processing."""

from __future__ import annotations

import imaplib
import json
import re
from pathlib import Path
from typing import Any

from .artifacts import generated_at


def uid_watermarks_path(state_root: Path) -> Path:
    return state_root / "runtime" / "context" / "uid-watermarks.json"


def load_uid_watermarks(state_root: Path) -> dict[str, Any]:
    path = uid_watermarks_path(state_root)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def save_uid_watermarks(state_root: Path, payload: dict[str, Any]) -> Path:
    path = uid_watermarks_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


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


def _decode_fetch_rows(fetch_data: list[bytes], folder: str) -> list[dict[str, Any]]:
    if not fetch_data:
        return []
    raw = fetch_data[0].decode() if isinstance(fetch_data[0], bytes) else str(fetch_data[0])
    payload = json.loads(raw)
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
        rows.append(item)
    return rows


def fetch_incremental_envelopes(
    state_root: Path,
    folders: list[str],
    imap_config: dict[str, Any],
    watermarks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if watermarks is None:
        watermarks = load_uid_watermarks(state_root)

    client = imaplib.IMAP4_SSL(str(imap_config["host"]), int(imap_config.get("port", 993)))
    client.login(str(imap_config["login"]), str(imap_config["password"]))

    new_envelopes: list[dict[str, Any]] = []
    updated_watermarks = dict(watermarks)
    uidvalidity_changed: list[str] = []
    sync_time = generated_at()

    try:
        for folder in folders:
            status, select_data = client.select(folder, readonly=True)
            if status != "OK":
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
                continue
            uids = _decode_uid_list(search_data)
            fetched_rows: list[dict[str, Any]] = []
            if uids:
                status, fetch_data = client.uid("FETCH", ",".join(str(uid) for uid in uids), "(ENVELOPE FLAGS)")
                if status == "OK":
                    fetched_rows = _decode_fetch_rows(fetch_data, folder)
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
    }
