"""Helpers for merging incremental Phase 1 context updates."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .artifacts import generated_at


def normalize_imap_envelope(imap_envelope: dict[str, Any], folder: str) -> dict[str, Any]:
    return {
        "id": str(imap_envelope.get("id", "") or ""),
        "folder": folder,
        "subject": str(imap_envelope.get("subject", "") or ""),
        "date": str(imap_envelope.get("date", "") or ""),
        "from": {
            "name": str(imap_envelope.get("from_name", "") or ""),
            "addr": str(imap_envelope.get("from_addr", "") or ""),
        },
        "has_attachment": bool(imap_envelope.get("has_attachment", False)),
        "flags": [str(flag) for flag in imap_envelope.get("flags", [])],
    }


def _load_existing_context(existing_path: Path) -> dict[str, Any]:
    if not existing_path.exists():
        return {
            "generated_at": "",
            "lookback_days": None,
            "owner_domain": "",
            "envelopes": [],
            "sampled_bodies": {},
            "stats": {},
        }
    payload = json.loads(existing_path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload
    return {
        "generated_at": "",
        "lookback_days": None,
        "owner_domain": "",
        "envelopes": [],
        "sampled_bodies": {},
        "stats": {},
    }


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def merge_incremental_context(
    existing_path: Path,
    new_envelopes: list[dict[str, Any]],
    new_bodies: dict[str, dict[str, Any]],
    *,
    owner_domain: str | None = None,
    lookback_days: int | None = None,
    folders_scanned: list[str] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    payload = _load_existing_context(existing_path)
    existing_envelopes = payload.get("envelopes", [])
    body_map = payload.get("sampled_bodies", {})
    stats = payload.get("stats", {})
    effective_lookback_days = (
        int(lookback_days)
        if lookback_days is not None
        else int(payload.get("lookback_days", 7) or 7)
    )

    if not isinstance(existing_envelopes, list):
        existing_envelopes = []
    if not isinstance(body_map, dict):
        body_map = {}
    if not isinstance(stats, dict):
        stats = {}

    merged_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in existing_envelopes:
        if not isinstance(row, dict):
            continue
        merged_by_key[(str(row.get("id", "") or ""), str(row.get("folder", "") or ""))] = row
    for row in new_envelopes:
        if not isinstance(row, dict):
            continue
        merged_by_key[(str(row.get("id", "") or ""), str(row.get("folder", "") or ""))] = row

    effective_now = _parse_datetime(now) if now else None
    cutoff = effective_now - timedelta(days=effective_lookback_days) if effective_now else None
    envelopes = list(merged_by_key.values())
    if cutoff is not None:
        envelopes = [
            row for row in envelopes
            if (parsed := _parse_datetime(str(row.get("date", "") or ""))) is not None and parsed >= cutoff
        ]

    envelopes.sort(key=lambda row: str(row.get("date", "") or ""), reverse=True)
    active_ids = {str(row.get("id", "") or "") for row in envelopes}

    merged_bodies = {str(key): value for key, value in body_map.items() if str(key) in active_ids}
    for key, value in new_bodies.items():
        if str(key) not in merged_bodies:
            merged_bodies[str(key)] = value

    updated_stats = dict(stats)
    updated_stats["total_envelopes"] = len(envelopes)
    updated_stats["sampled_bodies"] = len(merged_bodies)
    merged_folders: list[str] = []
    existing_folders = updated_stats.get("folders_scanned", [])
    if isinstance(existing_folders, list):
        for folder in existing_folders:
            text = str(folder or "")
            if text and text not in merged_folders:
                merged_folders.append(text)
    if folders_scanned is not None:
        for folder in folders_scanned:
            text = str(folder or "")
            if text and text not in merged_folders:
                merged_folders.append(text)
    else:
        for envelope in envelopes:
            if not isinstance(envelope, dict):
                continue
            text = str(envelope.get("folder", "") or "")
            if text and text not in merged_folders:
                merged_folders.append(text)
    if merged_folders:
        updated_stats["folders_scanned"] = merged_folders

    return {
        **payload,
        "generated_at": now or generated_at(),
        "owner_domain": owner_domain if owner_domain is not None else str(payload.get("owner_domain", "") or ""),
        "lookback_days": effective_lookback_days,
        "envelopes": envelopes,
        "sampled_bodies": merged_bodies,
        "stats": updated_stats,
    }
