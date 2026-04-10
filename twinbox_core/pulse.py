"""Activity pulse + thread snapshot projection.

Reads Phase 1 envelopes + Phase 4 queue artifacts → activity-pulse.json.
Ported from daytime_slice.py, simplified.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def _load_json(path: Path, default: object) -> object:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return content if isinstance(content, dict) else {}


def _parse_dt(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    if "T" not in normalized and re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:", normalized):
        normalized = normalized.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed


def _normalize_thread(subject: object) -> str:
    value = str(subject or "").lower()
    value = re.sub(r"^(\s*(re|fw|fwd|回复|转发|答复)\s*[:：])+\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[-_ ]?(20\d{6}|\d{8})$", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or "(no-subject)"


def _extract_tokens(text: object) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", str(text or ""))
    stop = {"re", "fw", "fwd", "回复", "转发", "答复", "请", "通知", "关于"}
    return [t.lower() for t in tokens if t.lower() not in stop]


def _load_envelopes(state_root: Path) -> list[dict[str, Any]]:
    raw = state_root / "runtime" / "validation" / "phase-1" / "raw" / "envelopes-merged.json"
    if raw.is_file():
        rows = _load_json(raw, [])
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    ctx = state_root / "runtime" / "context" / "phase1-context.json"
    data = _load_json(ctx, {})
    if isinstance(data, dict):
        rows = data.get("envelopes", [])
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def _queue_membership(state_root: Path) -> dict[str, dict[str, Any]]:
    root = state_root / "runtime" / "validation" / "phase-4"
    specs = [
        ("daily-urgent.yaml", "daily_urgent", "urgent"),
        ("pending-replies.yaml", "pending_replies", "pending"),
        ("sla-risks.yaml", "sla_risks", "sla_risk"),
    ]
    membership: dict[str, dict[str, Any]] = {}
    for filename, key, tag in specs:
        artifact = _load_yaml(root / filename)
        for row in artifact.get(key, []):
            if not isinstance(row, dict):
                continue
            tk = str(row.get("thread_key", "") or "")
            if not tk:
                continue
            slot = membership.setdefault(tk, {"queue_tags": []})
            slot["queue_tags"].append(tag)
            slot.setdefault("waiting_on", row.get("waiting_on"))
            slot.setdefault("why", row.get("why") or row.get("risk_description") or "")
    for slot in membership.values():
        slot["queue_tags"] = sorted(set(str(t) for t in slot.get("queue_tags", [])))
    return membership


def _load_queue_state(state_root: Path) -> dict[str, Any]:
    path = state_root / "runtime" / "context" / "user-queue-state.yaml"
    return _load_yaml(path)


def _is_hidden(thread_key: str, queue_state: dict[str, Any]) -> bool:
    for row in queue_state.get("completed", []):
        if isinstance(row, dict) and str(row.get("thread_key", "")) == thread_key:
            return True
    for row in queue_state.get("dismissed", []):
        if isinstance(row, dict) and str(row.get("thread_key", "")) == thread_key:
            return True
    return False


@dataclass
class ThreadSnapshot:
    thread_key: str
    latest_subject: str
    last_activity_at: str
    latest_message_ref: str
    new_message_count: int
    message_count: int
    unread_count: int
    queue_tags: list[str]
    waiting_on: str | None
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
            "unread_count": self.unread_count,
            "queue_tags": self.queue_tags,
            "waiting_on": self.waiting_on,
            "why": self.why,
            "fingerprint": self.fingerprint,
            "query_terms": self.query_terms,
            "score": self.score,
        }


def build_activity_pulse(state_root: Path, *, window_hours: int = 24) -> dict[str, Any]:
    envelopes = _load_envelopes(state_root)
    if not envelopes:
        raise RuntimeError("Missing envelopes. Run sync first.")

    queue_mem = _queue_membership(state_root)
    queue_state = _load_queue_state(state_root)
    cutoff = datetime.now(SHANGHAI) - timedelta(hours=window_hours)

    # Group by thread
    grouped: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for env in envelopes:
        parsed = _parse_dt(env.get("date"))
        if parsed is None:
            continue
        tk = _normalize_thread(env.get("subject"))
        grouped.setdefault(tk, []).append((parsed, env))

    snapshots: list[ThreadSnapshot] = []
    for tk, rows in grouped.items():
        if _is_hidden(tk, queue_state):
            continue
        rows.sort(key=lambda x: x[0], reverse=True)
        latest_dt, latest = rows[0]
        in_window = [r for r in rows if r[0] >= cutoff]
        q = queue_mem.get(tk, {})
        tags = list(q.get("queue_tags", []))
        ref = f"{latest.get('folder', 'INBOX')}#{latest.get('id', '')}"
        why = str(q.get("why", "") or "")
        if not why:
            why = f"最近{window_hours}小时新增 {len(in_window)} 封邮件" if in_window else "当前无新增邮件"
        score = len(in_window) * 10
        if "urgent" in tags:
            score += 40
        if "pending" in tags:
            score += 30
        if "sla_risk" in tags:
            score += 20
        unread = sum(1 for _, r in rows if "Seen" not in r.get("flags", []))
        fp = f"{ref}|{','.join(tags)}|{q.get('waiting_on', '')}"
        terms = sorted(set(_extract_tokens(tk) + _extract_tokens(latest.get("subject", ""))))
        snapshots.append(ThreadSnapshot(
            thread_key=tk, latest_subject=str(latest.get("subject", "")),
            last_activity_at=latest_dt.isoformat(), latest_message_ref=ref,
            new_message_count=len(in_window), message_count=len(rows),
            unread_count=unread, queue_tags=tags, waiting_on=q.get("waiting_on"),
            why=why, fingerprint=fp, query_terms=terms, score=score,
        ))

    snapshots.sort(key=lambda s: (s.score, s.last_activity_at), reverse=True)
    recent = [s for s in snapshots if s.new_message_count > 0][:20]
    attention = [s for s in snapshots if s.queue_tags][:20]

    return {
        "generated_at": _now_iso(),
        "window_hours": window_hours,
        "summary": {
            "tracked_threads": len(snapshots),
            "recent_activity_count": len(recent),
            "needs_attention_count": len(attention),
        },
        "recent_activity": [s.to_dict() for s in recent],
        "needs_attention": [s.to_dict() for s in attention],
        "thread_index": [s.to_dict() for s in snapshots],
    }


def write_activity_pulse(state_root: Path, **kwargs: Any) -> tuple[dict[str, Any], Path]:
    payload = build_activity_pulse(state_root, **kwargs)
    out = state_root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload, out


def load_activity_pulse(state_root: Path) -> dict[str, Any]:
    path = state_root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
    if not path.is_file():
        raise RuntimeError("Missing activity-pulse.json. Run sync first.")
    data = _load_json(path, {})
    if not isinstance(data, dict):
        raise RuntimeError("activity-pulse.json has unexpected structure")
    return data


def search_threads(query: str, state_root: Path, *, limit: int = 5) -> list[dict[str, Any]]:
    q = str(query or "").strip().lower()
    if not q:
        return []
    tokens = set(_extract_tokens(q))
    pulse = load_activity_pulse(state_root)
    index = pulse.get("thread_index", [])
    if not isinstance(index, list):
        return []
    matches: list[tuple[int, dict[str, Any]]] = []
    for item in index:
        if not isinstance(item, dict):
            continue
        tk = str(item.get("thread_key", "")).lower()
        subj = str(item.get("latest_subject", "")).lower()
        haystack = f"{tk}\n{subj}"
        terms = {str(t).lower() for t in item.get("query_terms", [])}
        score = 0
        if q == tk:
            score += 120
        if q in haystack:
            score += 80
        if tokens:
            score += 15 * len(tokens & terms)
        if score <= 0:
            continue
        m = dict(item)
        m["match_score"] = score + int(item.get("score", 0))
        matches.append((m["match_score"], m))
    matches.sort(key=lambda p: p[0], reverse=True)
    return [item for _, item in matches[:limit]]
