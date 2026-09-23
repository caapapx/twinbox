"""Induced taxonomy drafts. Query assignment never calls a model."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .embeddings import cosine, sidecar_path
from .pack import load_active_pack, validate_pack

CATEGORY_CAP = 12
EXCERPT_CHARS = 280
OTHER_ID = "other"
WINDOWS = (7, 30, 90)
_POLICY = {"watch", "reference"}


def excerpt(text: object) -> str:
    return str(text or "").strip()[:EXCERPT_CHARS]


def _key(action: object) -> str:
    text = " ".join(str(action or "").split()).lower()
    return text or OTHER_ID


def draft_path(state_root: Path) -> Path:
    return Path(state_root) / "packs" / "taxonomy-draft.yaml"


def drift_path(state_root: Path) -> Path:
    return Path(state_root) / "runtime" / "context" / "taxonomy-drift.json"


def build_draft(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Group existing rows by owner action. No network and no model call."""
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _key(row.get("owner_action"))
        bucket = groups.setdefault(key, {"count": 0, "vectors": []})
        bucket["count"] += 1
        vector = row.get("vector")
        if isinstance(vector, list) and vector and all(isinstance(x, (int, float)) for x in vector):
            bucket["vectors"].append([float(x) for x in vector])
    ranked = sorted(groups.items(), key=lambda item: (-item[1]["count"], item[0]))
    kept = [item for item in ranked if item[0] != OTHER_ID][:CATEGORY_CAP]
    overflow = [item for item in ranked if item[0] != OTHER_ID][CATEGORY_CAP:]
    other = groups.get(OTHER_ID, {"count": 0, "vectors": []})
    for _key_name, bucket in overflow:
        other["count"] += bucket["count"]
        other["vectors"].extend(bucket["vectors"])
    categories = [_category(key, bucket) for key, bucket in kept]
    if other["count"]:
        categories.append(_category(OTHER_ID, other))
    return {"status": "draft", "categories": categories}


def _category(key: str, bucket: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": key if key == OTHER_ID else "c" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:8],
        "owner_action": "" if key == OTHER_ID else key,
        "value_policy": "reference" if key == OTHER_ID else "watch",
        "count": bucket["count"],
    }
    vectors = bucket["vectors"]
    if vectors and all(len(v) == len(vectors[0]) for v in vectors):
        width = len(vectors[0])
        item["centroid"] = [sum(v[i] for v in vectors) / len(vectors) for i in range(width)]
    return item


def confirm_draft(pack: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    """Copy a draft into the pack. The draft object itself stays a draft."""
    live = {
        "status": "live",
        "categories": [
            {
                "id": item["id"],
                "owner_action": item.get("owner_action") or "",
                "value_policy": item["value_policy"] if item.get("value_policy") in _POLICY else "reference",
                **({"centroid": item["centroid"]} if isinstance(item.get("centroid"), list) else {}),
            }
            for item in draft.get("categories") or []
            if isinstance(item, dict) and item.get("id")
        ],
    }
    updated = dict(pack)
    updated["taxonomy"] = live
    return updated


def classify_for_query(
    pack: dict[str, Any] | None,
    vector: list[float] | None,
    *,
    margin: float = 0.05,
) -> dict[str, Any] | None:
    """Assign from a confirmed pack only. Never embeds and never reads a draft."""
    tax = pack.get("taxonomy") if isinstance(pack, dict) else None
    if not isinstance(tax, dict) or tax.get("status") != "live":
        return None
    scored: list[tuple[float, str]] = []
    for item in tax.get("categories") or []:
        if not isinstance(item, dict):
            continue
        centroid = item.get("centroid")
        if not isinstance(centroid, list):
            continue
        scored.append((cosine(vector or [], centroid), str(item.get("id") or "")))
    scored = [pair for pair in scored if pair[1]]
    if not scored:
        return None
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    best, second = scored[0], scored[1] if len(scored) > 1 else None
    if second is not None and best[0] - second[0] < margin:
        return {"defer": True}
    return {"id": best[1], "score": best[0], "defer": False}


def stop_reason(
    batch_changes: list[int],
    *,
    other_ratio: float | None = None,
    budget_left: int = 1,
) -> str | None:
    """Return stable, coverage, or budget. None means the draft run may continue."""
    if budget_left <= 0:
        return "budget"
    if other_ratio is not None and other_ratio <= 0.15:
        return "coverage"
    if len(batch_changes) >= 3 and all(change <= 1 for change in batch_changes[-3:]):
        return "stable"
    return None


def drift_note(live_ids: list[str], draft_ids: list[str]) -> dict[str, Any]:
    """Record a drift prompt. Does not replace the live category list."""
    live, draft = set(live_ids), set(draft_ids)
    return {
        "kind": "taxonomy_drift",
        "added": sorted(draft - live),
        "removed": sorted(live - draft),
    }


def _parse_date(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _load_json(path: Path, default: object) -> object:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _owner_action_from_labels(state_root: Path) -> dict[str, str]:
    phase4 = Path(state_root) / "runtime" / "validation" / "phase-4"
    actions: dict[str, str] = {}
    mapping = {
        "pending-replies.yaml": ("pending_replies", "reply"),
        "daily-urgent.yaml": ("daily_urgent", "act"),
        "sla-risks.yaml": ("sla_risks", "follow_up"),
    }
    for name, (key, default) in mapping.items():
        path = phase4 / name
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        rows = data.get(key) if isinstance(data, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            thread = str(row.get("thread_key") or row.get("subject") or "").strip().lower()
            if not thread:
                continue
            waiting = str(row.get("waiting_on") or "").strip().lower()
            actions[thread] = waiting or default
    return actions


def load_induction_rows(state_root: Path, lookback_days: int) -> list[dict[str, Any]]:
    """Build induction rows from retained envelopes and existing labels. No IMAP, no embed."""
    root = Path(state_root)
    ctx = _load_json(root / "runtime" / "context" / "phase1-context.json", {})
    envelopes = ctx.get("envelopes") if isinstance(ctx, dict) else []
    if not isinstance(envelopes, list):
        envelopes = []
    bodies = ctx.get("sampled_bodies") if isinstance(ctx, dict) else {}
    if not isinstance(bodies, dict):
        bodies = {}
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, lookback_days))
    actions = _owner_action_from_labels(root)
    rows: list[dict[str, Any]] = []
    for env in envelopes:
        if not isinstance(env, dict):
            continue
        when = _parse_date(env.get("date") or env.get("internal_date"))
        if when is not None and when < cutoff:
            continue
        folder = str(env.get("folder") or "INBOX")
        uid = str(env.get("id") or "")
        subject = str(env.get("subject") or "")
        body = ""
        entry = bodies.get(f"{folder}#{uid}") or bodies.get(uid) or {}
        if isinstance(entry, dict):
            body = str(entry.get("body") or "")
        elif isinstance(entry, str):
            body = entry
        thread = subject.strip().lower()
        vector = None
        side = sidecar_path(root, folder, uid) if uid else None
        if side is not None and side.is_file():
            payload = _load_json(side, {})
            if isinstance(payload, dict) and isinstance(payload.get("vector"), list):
                vector = payload["vector"]
        rows.append({
            "owner_action": actions.get(thread, ""),
            "subject": subject,
            "excerpt": excerpt(f"{subject}\n{body}"),
            "vector": vector,
            "lookback_days": lookback_days,
        })
    return rows


def _category_ids(draft: dict[str, Any]) -> list[str]:
    return [
        str(item.get("id"))
        for item in draft.get("categories") or []
        if isinstance(item, dict) and item.get("id")
    ]


def _other_ratio(draft: dict[str, Any]) -> float:
    total = sum(
        int(item.get("count") or 0)
        for item in draft.get("categories") or []
        if isinstance(item, dict)
    )
    if total <= 0:
        return 1.0
    other = next(
        (
            int(item.get("count") or 0)
            for item in draft.get("categories") or []
            if isinstance(item, dict) and item.get("id") == OTHER_ID
        ),
        0,
    )
    return other / total


def induce(
    state_root: Path,
    *,
    lookback_days: int | None = None,
    budget: int = 3,
) -> dict[str, Any]:
    """Expand 7→30→90 until a stop fires. Writes a draft only; never makes it live."""
    root = Path(state_root)
    windows = [lookback_days] if lookback_days else list(WINDOWS)
    batch_changes: list[int] = []
    previous: set[str] = set()
    draft: dict[str, Any] = {"status": "draft", "categories": []}
    used = 0
    stop = None
    for days in windows:
        used += 1
        draft = build_draft(load_induction_rows(root, int(days)))
        draft["lookback_days"] = int(days)
        ids = set(_category_ids(draft))
        change = len(ids ^ previous) if previous else len(ids)
        batch_changes.append(change)
        previous = ids
        stop = stop_reason(
            batch_changes,
            other_ratio=_other_ratio(draft),
            budget_left=budget - used,
        )
        if stop:
            break
    draft["stop"] = stop or "windows_exhausted"
    path = draft_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(draft, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {
        "ok": True,
        "status": "draft",
        "path": str(path),
        "lookback_days": draft.get("lookback_days"),
        "categories": len(draft.get("categories") or []),
        "stop": draft["stop"],
        "other_ratio": _other_ratio(draft),
    }


def confirm(state_root: Path) -> dict[str, Any]:
    """Promote the on-disk draft into packs/user.yaml. Query stays draft-blind until this returns."""
    root = Path(state_root)
    path = draft_path(root)
    if not path.is_file():
        return {"ok": False, "error": "taxonomy_draft_missing"}
    try:
        draft = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {"ok": False, "error": "taxonomy_draft_corrupt"}
    if not isinstance(draft, dict) or draft.get("status") != "draft":
        return {"ok": False, "error": "taxonomy_draft_invalid"}
    pack = load_active_pack(root) or {"id": "user", "version": "1.0.0"}
    updated = validate_pack(confirm_draft(pack, draft))
    user = root / "packs" / "user.yaml"
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text(yaml.safe_dump(updated, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {
        "ok": True,
        "status": "live",
        "path": str(user),
        "fingerprint": updated.get("fingerprint"),
        "categories": len((updated.get("taxonomy") or {}).get("categories") or []),
    }


def record_drift(state_root: Path) -> dict[str, Any]:
    """Compare live ids to a fresh 7-day draft. Writes a note; does not change the live pack."""
    root = Path(state_root)
    pack = load_active_pack(root) or {}
    tax = pack.get("taxonomy") if isinstance(pack, dict) else None
    live_ids = [
        str(item.get("id"))
        for item in (tax.get("categories") if isinstance(tax, dict) else []) or []
        if isinstance(item, dict) and item.get("id")
    ]
    draft = build_draft(load_induction_rows(root, WINDOWS[0]))
    note = drift_note(live_ids, _category_ids(draft))
    note["recorded_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = drift_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(note, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(path), "note": note}
