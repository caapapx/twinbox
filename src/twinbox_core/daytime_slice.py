"""Daytime activity pulse projection and thread progress lookup."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .paths import resolve_state_root as resolve_shared_state_root

SHANGHAI = ZoneInfo("Asia/Shanghai")


class DaytimeSliceError(RuntimeError):
    """Raised when daytime projection artifacts cannot be built or read."""


@dataclass(frozen=True)
class ThreadSnapshot:
    """Stable thread summary stored in activity-pulse artifacts."""

    thread_key: str
    latest_subject: str
    last_activity_at: str
    latest_message_ref: str
    new_message_count: int
    message_count: int
    unread_count: int
    queue_tags: list[str]
    waiting_on: str | None
    flow: str | None
    stage: str | None
    why: str
    fingerprint: str
    query_terms: list[str]
    score: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_key": self.thread_key,
            "latest_subject": self.latest_subject,
            "last_activity_at": self.last_activity_at,
            "latest_message_ref": self.latest_message_ref,
            "new_message_count": self.new_message_count,
            "message_count": self.message_count,
            "unread_count": getattr(self, "unread_count", 0),
            "queue_tags": self.queue_tags,
            "waiting_on": self.waiting_on,
            "flow": self.flow,
            "stage": self.stage,
            "why": self.why,
            "fingerprint": self.fingerprint,
            "query_terms": self.query_terms,
            "score": self.score,
        }


def generated_at() -> str:
    """Return an ISO timestamp in Asia/Shanghai."""
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def resolve_state_root(root: str | Path | None = None) -> Path:
    """Resolve the canonical runtime root for projections."""
    if root is None:
        return resolve_shared_state_root(Path.cwd())
    return Path(root).expanduser().resolve()


def phase4_dir(state_root: Path) -> Path:
    return state_root / "runtime" / "validation" / "phase-4"


def activity_pulse_path(state_root: Path) -> Path:
    return phase4_dir(state_root) / "activity-pulse.json"


def dedupe_state_path(state_root: Path) -> Path:
    return state_root / "runtime" / "context" / "activity-pulse-state.json"


def _load_json_if_exists(path: Path, default: object) -> object:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _load_yaml_if_exists(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return content if isinstance(content, dict) else {}


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    if re.search(r"[+-]\d{4}$", normalized):
        normalized = f"{normalized[:-5]}{normalized[-5:-2]}:{normalized[-2:]}"
    if "T" not in normalized and re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:", normalized):
        normalized = normalized.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=SHANGHAI)
    return parsed


def _normalize_thread(subject: object) -> str:
    value = str(subject or "").lower()
    value = re.sub(r"^(\s*(re|fw|fwd|回复|转发|答复)\s*[:：])+\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[-_ ]?(20\d{6}|\d{8})$", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or "(no-subject)"


def _extract_tokens(text: object) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", str(text or ""))
    stop_words = {"re", "fw", "fwd", "回复", "转发", "答复", "请", "通知", "关于"}
    return [token.lower() for token in tokens if token.lower() not in stop_words]


def _load_phase1_envelopes(state_root: Path) -> list[dict[str, Any]]:
    raw_path = state_root / "runtime" / "validation" / "phase-1" / "raw" / "envelopes-merged.json"
    if raw_path.is_file():
        rows = _load_json_if_exists(raw_path, [])
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]

    context_path = state_root / "runtime" / "context" / "phase1-context.json"
    context = _load_json_if_exists(context_path, {})
    if isinstance(context, dict):
        rows = context.get("envelopes", [])
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _queue_membership(state_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    root = phase4_dir(state_root)
    queue_specs = (
        ("daily-urgent.yaml", "daily_urgent", "urgent"),
        ("pending-replies.yaml", "pending_replies", "pending"),
        ("sla-risks.yaml", "sla_risks", "sla_risk"),
    )
    membership: dict[str, dict[str, Any]] = {}
    generated: dict[str, str] = {}
    for filename, queue_key, tag in queue_specs:
        artifact = _load_yaml_if_exists(root / filename)
        generated[tag] = str(artifact.get("generated_at", "") or "")
        for row in artifact.get(queue_key, []):
            if not isinstance(row, dict):
                continue
            thread_key = str(row.get("thread_key", "") or "")
            if not thread_key:
                continue
            slot = membership.setdefault(thread_key, {"queue_tags": []})
            slot["queue_tags"].append(tag)
            slot.setdefault("flow", row.get("flow"))
            slot.setdefault("stage", row.get("stage"))
            slot.setdefault("waiting_on", row.get("waiting_on"))
            slot.setdefault("why", row.get("why") or row.get("risk_description") or "")
    for slot in membership.values():
        slot["queue_tags"] = sorted(set(str(tag) for tag in slot.get("queue_tags", [])))
    return membership, generated


def _load_dedupe_state(state_root: Path) -> dict[str, Any]:
    state = _load_json_if_exists(dedupe_state_path(state_root), {})
    return state if isinstance(state, dict) else {}


def _save_dedupe_state(state_root: Path, state: dict[str, Any]) -> Path:
    path = dedupe_state_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _state_marker(queue_state: dict[str, Any]) -> str:
    tags = ",".join(sorted(str(tag) for tag in queue_state.get("queue_tags", [])))
    waiting_on = str(queue_state.get("waiting_on", "") or "")
    flow = str(queue_state.get("flow", "") or "")
    stage = str(queue_state.get("stage", "") or "")
    return "|".join((tags, waiting_on, flow, stage))


def _build_thread_index(
    envelopes: list[dict[str, Any]],
    queue_membership: dict[str, dict[str, Any]],
    *,
    window_hours: int,
) -> list[ThreadSnapshot]:
    cutoff = datetime.now(SHANGHAI) - timedelta(hours=window_hours)
    grouped: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for envelope in envelopes:
        parsed = _parse_datetime(envelope.get("date"))
        if parsed is None:
            continue
        thread_key = _normalize_thread(envelope.get("subject"))
        grouped.setdefault(thread_key, []).append((parsed, envelope))

    snapshots: list[ThreadSnapshot] = []
    for thread_key, rows in grouped.items():
        rows.sort(key=lambda item: item[0], reverse=True)
        latest_dt, latest = rows[0]
        in_window = [row for row in rows if row[0] >= cutoff]
        queue_state = queue_membership.get(thread_key, {})
        queue_tags = list(queue_state.get("queue_tags", []))
        latest_message_ref = f"{latest.get('folder', 'INBOX')}#{latest.get('id', '')}"
        why = str(queue_state.get("why", "") or "")
        if not why:
            why = f"最近{window_hours}小时新增 {len(in_window)} 封邮件" if in_window else "当前无新增邮件"
        score = len(in_window) * 10
        if "urgent" in queue_tags:
            score += 40
        if "pending" in queue_tags:
            score += 30
        if "sla_risk" in queue_tags:
            score += 20
        fingerprint = f"{latest_message_ref}|{_state_marker(queue_state)}"
        query_terms = sorted(set(_extract_tokens(thread_key) + _extract_tokens(latest.get("subject", ""))))
        
        unread_count = sum(1 for _, row in rows if "Seen" not in row.get("flags", []))

        snapshots.append(
            ThreadSnapshot(
                thread_key=thread_key,
                latest_subject=str(latest.get("subject", "") or ""),
                last_activity_at=latest_dt.isoformat(),
                latest_message_ref=latest_message_ref,
                new_message_count=len(in_window),
                message_count=len(rows),
                unread_count=unread_count,
                queue_tags=queue_tags,
                waiting_on=(
                    None if queue_state.get("waiting_on") in {None, ""} else str(queue_state.get("waiting_on"))
                ),
                flow=None if queue_state.get("flow") in {None, ""} else str(queue_state.get("flow")),
                stage=None if queue_state.get("stage") in {None, ""} else str(queue_state.get("stage")),
                why=why,
                fingerprint=fingerprint,
                query_terms=query_terms,
                score=score,
            )
        )
    snapshots.sort(key=lambda item: (item.score, item.last_activity_at), reverse=True)
    return snapshots


def _filter_notifiable(
    snapshots: list[ThreadSnapshot],
    delivered: dict[str, Any],
    *,
    top_k: int,
) -> list[ThreadSnapshot]:
    items: list[ThreadSnapshot] = []
    for snapshot in snapshots:
        if snapshot.new_message_count <= 0 and not snapshot.queue_tags:
            continue
        previous = delivered.get(snapshot.thread_key, {})
        if previous.get("fingerprint") == snapshot.fingerprint:
            continue
        items.append(snapshot)
        if len(items) >= top_k:
            break
    return items


def build_activity_pulse(
    state_root: str | Path | None = None,
    *,
    window_hours: int = 24,
    top_k: int = 3,
) -> dict[str, Any]:
    """Build the daytime activity pulse from existing artifacts."""
    resolved_root = resolve_state_root(state_root)
    envelopes = _load_phase1_envelopes(resolved_root)
    if not envelopes:
        raise DaytimeSliceError(
            "Missing Phase 1 envelopes.\nRun Phase 1 loading first or a scheduled daytime sync."
        )

    queue_membership, queue_generated = _queue_membership(resolved_root)
    snapshots = _build_thread_index(envelopes, queue_membership, window_hours=window_hours)
    dedupe_state = _load_dedupe_state(resolved_root)
    delivered = dedupe_state.get("threads", {}) if isinstance(dedupe_state.get("threads"), dict) else {}
    notifiable = _filter_notifiable(snapshots, delivered, top_k=top_k)
    recent_activity = [item for item in snapshots if item.new_message_count > 0][:20]
    needs_attention = [item for item in snapshots if item.queue_tags][:20]

    payload = {
        "generated_at": generated_at(),
        "window_hours": window_hours,
        "top_k": top_k,
        "summary": {
            "tracked_threads": len(snapshots),
            "recent_activity_count": len(recent_activity),
            "needs_attention_count": len(needs_attention),
            "notifiable_count": len(notifiable),
            "phase4_generated_at": queue_generated,
        },
        "notify_payload": {
            "generated_at": generated_at(),
            "stale": False,
            "urgent_top_k": [item.to_dict() for item in notifiable],
            "pending_count": len([item for item in needs_attention if "pending" in item.queue_tags]),
            "summary": (
                "最近24小时无新增或状态变化"
                if not notifiable
                else f"最近24小时有 {len(notifiable)} 个线程值得推送"
            ),
        },
        "notifiable_items": [item.to_dict() for item in notifiable],
        "recent_activity": [item.to_dict() for item in recent_activity],
        "needs_attention": [item.to_dict() for item in needs_attention],
        "thread_index": [item.to_dict() for item in snapshots],
    }
    return payload


def write_activity_pulse(
    state_root: str | Path | None = None,
    *,
    window_hours: int = 24,
    top_k: int = 3,
    update_dedupe: bool = False,
) -> tuple[dict[str, Any], Path]:
    """Build and persist the activity pulse artifact."""
    resolved_root = resolve_state_root(state_root)
    payload = build_activity_pulse(resolved_root, window_hours=window_hours, top_k=top_k)
    out_path = activity_pulse_path(resolved_root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if update_dedupe:
        state = _load_dedupe_state(resolved_root)
        threads = state.setdefault("threads", {})
        for item in payload.get("notifiable_items", []):
            if not isinstance(item, dict):
                continue
            thread_key = str(item.get("thread_key", "") or "")
            if not thread_key:
                continue
            threads[thread_key] = {
                "fingerprint": item.get("fingerprint", ""),
                "last_notified_at": payload["generated_at"],
                "latest_message_ref": item.get("latest_message_ref", ""),
            }
        state["generated_at"] = payload["generated_at"]
        _save_dedupe_state(resolved_root, state)

    return payload, out_path


def load_activity_pulse(state_root: str | Path | None = None) -> dict[str, Any]:
    """Load the persisted activity pulse artifact."""
    resolved_root = resolve_state_root(state_root)
    path = activity_pulse_path(resolved_root)
    if not path.is_file():
        raise DaytimeSliceError(
            "Missing activity-pulse.json.\nRun `twinbox-orchestrate schedule --job daytime-sync` first."
        )
    payload = _load_json_if_exists(path, {})
    if not isinstance(payload, dict):
        raise DaytimeSliceError("activity-pulse.json has unexpected structure")
    return payload


def search_activity_pulse(
    query: str,
    state_root: str | Path | None = None,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search thread progress by thread key, subject fragment, or business keyword."""
    query_text = str(query or "").strip().lower()
    if not query_text:
        return []
    query_tokens = set(_extract_tokens(query_text))
    payload = load_activity_pulse(state_root)
    thread_index = payload.get("thread_index", [])
    if not isinstance(thread_index, list):
        return []

    matches: list[tuple[int, dict[str, Any]]] = []
    for item in thread_index:
        if not isinstance(item, dict):
            continue
        thread_key = str(item.get("thread_key", "") or "")
        latest_subject = str(item.get("latest_subject", "") or "")
        haystack = f"{thread_key}\n{latest_subject}".lower()
        terms = {str(term).lower() for term in item.get("query_terms", []) if isinstance(term, str)}

        score = 0
        if query_text == thread_key:
            score += 120
        if query_text in haystack:
            score += 80
        if query_tokens:
            score += 15 * len(query_tokens & terms)
        if score <= 0:
            continue
        match = dict(item)
        match["match_score"] = score + int(item.get("score", 0) or 0)
        matches.append((match["match_score"], match))

    matches.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in matches[:limit]]
