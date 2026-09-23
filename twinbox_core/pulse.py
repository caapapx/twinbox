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

from .recipient import aggregate_thread_recipient_role

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


_DEFAULT_PREFIXES = ("re", "fw", "fwd", "回复", "转发", "答复")
_PREFIX_RE: re.Pattern[str] | None = None
_BULK_PRECEDENCE = {"bulk", "list", "junk"}


def _prefix_re() -> re.Pattern[str]:
    global _PREFIX_RE
    if _PREFIX_RE is not None:
        return _PREFIX_RE
    data = _load_yaml(Path(__file__).resolve().parents[1] / "config" / "thread-prefixes.yaml")
    raw = data.get("prefixes")
    prefixes = [str(item).strip() for item in raw if str(item).strip()] if isinstance(raw, list) else []
    chosen = prefixes or list(_DEFAULT_PREFIXES)
    pattern = "|".join(re.escape(item) for item in chosen)
    _PREFIX_RE = re.compile(rf"^(\s*(?:{pattern})\s*[:：])+\s*", re.IGNORECASE)
    return _PREFIX_RE


def normalize_thread_key(subject: object) -> str:
    return _normalize_thread(subject)


def _normalize_thread(subject: object) -> str:
    value = _prefix_re().sub("", str(subject or "").lower())
    value = re.sub(r"[-_ ]?(20\d{6}|\d{8})$", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value or "(no-subject)"


def _angle_ids(value: object) -> list[str]:
    return [item.lower() for item in re.findall(r"<[^>]+>", str(value or ""))]


def _group_envelopes(envelopes: list[dict[str, Any]]) -> dict[str, list[tuple[datetime, dict[str, Any]]]]:
    """Link replies by References, then key each group by its earliest subject."""
    dated: list[tuple[datetime, dict[str, Any]]] = []
    id_index: dict[str, int] = {}
    for env in envelopes:
        parsed = _parse_dt(env.get("date"))
        if parsed is None or not isinstance(env, dict):
            continue
        dated.append((parsed, env))
        for mid in _angle_ids(env.get("message_id")):
            id_index.setdefault(mid, len(dated) - 1)
    parent = list(range(len(dated)))

    def find(idx: int) -> int:
        while parent[idx] != idx:
            parent[idx] = parent[parent[idx]]
            idx = parent[idx]
        return idx

    for idx, (_, env) in enumerate(dated):
        refs = _angle_ids(env.get("in_reply_to")) + _angle_ids(env.get("references"))
        for ref in refs:
            other = id_index.get(ref)
            if other is not None:
                parent[find(idx)] = find(other)
    buckets: dict[int, list[tuple[datetime, dict[str, Any]]]] = {}
    for idx, row in enumerate(dated):
        buckets.setdefault(find(idx), []).append(row)
    grouped: dict[str, list[tuple[datetime, dict[str, Any]]]] = {}
    for members in buckets.values():
        earliest = min(members, key=lambda item: item[0])[1]
        key = _normalize_thread(earliest.get("subject"))
        grouped.setdefault(key, []).extend(members)
    return grouped


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
            tk = normalize_thread_key(row.get("thread_key", "") or "")
            if not tk:
                continue
            slot = membership.setdefault(tk, {"queue_tags": []})
            slot["queue_tags"].append(tag)
            slot.setdefault("waiting_on", row.get("waiting_on"))
            slot.setdefault("deadline", row.get("deadline"))
            slot.setdefault("why", row.get("why") or row.get("risk_description") or "")
            if row.get("evidence_basis") and "evidence_basis" not in slot:
                slot["evidence_basis"] = row.get("evidence_basis")
            if row.get("action_target") and "action_target" not in slot:
                slot["action_target"] = row.get("action_target")
            if row.get("evidence_refs") and "evidence_refs" not in slot:
                slot["evidence_refs"] = row.get("evidence_refs")
    for slot in membership.values():
        slot["queue_tags"] = sorted(set(str(t) for t in slot.get("queue_tags", [])))
    return membership


def _load_action_verbs() -> set[str]:
    root = Path(__file__).resolve().parents[1]
    path = root / "config" / "action-verbs.yaml"
    data = _load_yaml(path)
    verbs = data.get("verbs", [])
    if isinstance(verbs, list):
        return {str(v).strip() for v in verbs if str(v).strip()}
    return {"请审批", "请确认", "请登记", "请处理"}


# Pack-declared pulse score weights.  When a factor is missing or empty in the
# active pack, the engine falls back to these exact defaults so an undeclared
# pack keeps the historical scores.
_FACTOR_DEFAULTS = {
    "recent_window": 10,
    "urgent": 40,
    "pending": 30,
    "sla_risk": 20,
    "sla_aging_48h": -25,
    "action_verb": 15,
}


def _load_value_factors(state_root: Path) -> dict[str, int]:
    """Resolve pulse score factors from the active pack, defaulting each gap."""
    try:
        from .pack import load_active_pack
        pack = load_active_pack(state_root)
    except Exception:
        pack = None
    declared: dict[Any, Any] = {}
    if isinstance(pack, dict):
        ranking = pack.get("value_ranking")
        if isinstance(ranking, dict):
            factors = ranking.get("factors")
            if isinstance(factors, dict):
                declared = factors
    factors: dict[str, int] = {}
    for key, default in _FACTOR_DEFAULTS.items():
        value = declared.get(key)
        factors[key] = value if type(value) is int else default
    return factors


def _queue_join_diagnostics(state_root: Path, snapshots: list[ThreadSnapshot]) -> list[dict[str, str]]:
    known = {s.thread_key for s in snapshots}
    misses: list[dict[str, str]] = []
    root = state_root / "runtime" / "validation" / "phase-4"
    for filename, key in (
        ("daily-urgent.yaml", "daily_urgent"),
        ("pending-replies.yaml", "pending_replies"),
        ("sla-risks.yaml", "sla_risks"),
    ):
        artifact = _load_yaml(root / filename)
        for row in artifact.get(key, []):
            if not isinstance(row, dict):
                continue
            raw = str(row.get("thread_key", "") or "")
            tk = normalize_thread_key(raw)
            if tk and tk not in known:
                misses.append({"artifact": filename, "thread_key": raw, "normalized": tk})
    return misses


def _load_queue_state(state_root: Path) -> dict[str, Any]:
    path = state_root / "runtime" / "context" / "user-queue-state.yaml"
    return _load_yaml(path)


def _is_valid_reopen(env: dict[str, Any], owner: str) -> bool:
    sender = str(env.get("from_addr") or "").lower()
    if owner and sender == owner.lower():
        return False
    if str(env.get("list_id") or "").strip():
        return False
    if str(env.get("auto_submitted") or "").strip():
        return False
    if str(env.get("precedence") or "").strip().lower() in _BULK_PRECEDENCE:
        return False
    return True


def _is_direct(env: dict[str, Any]) -> bool:
    return str(env.get("recipient_role") or "") in {"to", "direct"}


def _dismiss_requires_direct(state_root: Path) -> bool:
    try:
        from .pack import load_active_pack
        pack = load_active_pack(state_root)
    except Exception:
        return False
    reopen = pack.get("reopen") if isinstance(pack, dict) else None
    dismissed = reopen.get("dismissed") if isinstance(reopen, dict) else None
    return bool(dismissed.get("require_direct")) if isinstance(dismissed, dict) else False


def _hide_decision(
    keys: set[str],
    rows: list[tuple[datetime, dict[str, Any]]],
    queue_state: dict[str, Any],
    *,
    owner: str,
    require_direct: bool,
) -> tuple[bool, str]:
    """Return (hidden, reopened_reason). A hide without a timestamp stays hidden."""
    matched: list[tuple[str, datetime | None]] = []
    for bucket in ("completed", "dismissed"):
        for row in queue_state.get(bucket, []):
            if isinstance(row, dict) and str(row.get("thread_key") or "") in keys:
                stamp = row.get("completed_at") if bucket == "completed" else row.get("dismissed_at")
                matched.append((bucket, _parse_dt(stamp)))
    if not matched:
        return False, ""
    if any(stamp is None for _, stamp in matched):
        return True, ""
    bucket, cutoff = max(matched, key=lambda item: item[1] or datetime.min.replace(tzinfo=SHANGHAI))
    for when, env in rows:
        if when <= cutoff:
            continue
        if not _is_valid_reopen(env, owner):
            continue
        if bucket == "dismissed" and require_direct and not _is_direct(env):
            continue
        return False, "valid_new_message"
    return True, ""


def _thread_keys(thread_key: str, rows: list[tuple[datetime, dict[str, Any]]]) -> set[str]:
    keys = {thread_key}
    for _, env in rows:
        keys.add(_normalize_thread(env.get("subject")))
    return keys


def hidden_thread_keys(state_root: Path) -> set[str]:
    """Thread keys still completed/dismissed after valid-new-mail reopen."""
    queue_state = _load_queue_state(state_root)
    grouped = _group_envelopes(_load_envelopes(state_root))
    from .config import owner_email
    owner = owner_email()
    require_direct = _dismiss_requires_direct(state_root)
    hidden: set[str] = set()
    seen: set[str] = set()
    for thread_key, rows in grouped.items():
        keys = _thread_keys(thread_key, rows)
        seen |= keys
        stays, _reason = _hide_decision(keys, rows, queue_state, owner=owner, require_direct=require_direct)
        if stays:
            hidden |= keys
    for bucket in ("completed", "dismissed"):
        for row in queue_state.get(bucket, []):
            if not isinstance(row, dict):
                continue
            tk = str(row.get("thread_key") or "")
            if tk and tk not in seen:
                hidden.add(tk)
    return hidden


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
    recipient_role: str = "unknown"
    latest_recipient_role: str = "unknown"
    action_hint: str = ""
    evidence_basis: str = ""
    action_target: str = ""
    evidence_refs: list[str] | None = None
    reopened_reason: str = ""
    deadline: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "thread_key": self.thread_key,
            "latest_subject": self.latest_subject,
            "last_activity_at": self.last_activity_at,
            "latest_message_ref": self.latest_message_ref,
            "new_message_count": self.new_message_count,
            "message_count": self.message_count,
            "unread_count": self.unread_count,
            "queue_tags": self.queue_tags,
            "waiting_on": self.waiting_on,
            "deadline": self.deadline,
            "why": self.why,
            "fingerprint": self.fingerprint,
            "query_terms": self.query_terms,
            "score": self.score,
            "recipient_role": self.recipient_role,
            "latest_recipient_role": self.latest_recipient_role,
            "action_hint": self.action_hint,
        }
        if self.evidence_basis:
            out["evidence_basis"] = self.evidence_basis
        if self.action_target:
            out["action_target"] = self.action_target
        if self.evidence_refs:
            out["evidence_refs"] = self.evidence_refs
        if self.reopened_reason:
            out["reopened_reason"] = self.reopened_reason
        return out


def build_activity_pulse(state_root: Path, *, window_hours: int = 24) -> dict[str, Any]:
    envelopes = _load_envelopes(state_root)
    if not envelopes:
        raise RuntimeError("Missing envelopes. Run sync first.")

    queue_mem = _queue_membership(state_root)
    queue_state = _load_queue_state(state_root)
    cutoff = datetime.now(SHANGHAI) - timedelta(hours=window_hours)
    from .config import owner_email
    owner = owner_email()
    require_direct = _dismiss_requires_direct(state_root)
    grouped = _group_envelopes(envelopes)

    snapshots: list[ThreadSnapshot] = []
    hidden_keys: set[str] = set()
    reopened: dict[str, str] = {}
    factors = _load_value_factors(state_root)
    for tk, rows in grouped.items():
        keys = _thread_keys(tk, rows)
        stays, reason = _hide_decision(keys, rows, queue_state, owner=owner, require_direct=require_direct)
        if stays:
            hidden_keys.add(tk)
        elif reason:
            reopened[tk] = reason
        rows.sort(key=lambda x: x[0], reverse=True)
        latest_dt, latest = rows[0]
        in_window = [r for r in rows if r[0] >= cutoff]
        q = queue_mem.get(tk, {})
        tags = list(q.get("queue_tags", []))
        ref = f"{latest.get('folder', 'INBOX')}#{latest.get('id', '')}"
        why = str(q.get("why", "") or "")
        if not why:
            why = f"最近{window_hours}小时新增 {len(in_window)} 封邮件" if in_window else "当前无新增邮件"
        score = len(in_window) * factors["recent_window"]
        if "urgent" in tags:
            score += factors["urgent"]
        if "pending" in tags:
            score += factors["pending"]
        if "sla_risk" in tags:
            score += factors["sla_risk"]
            age_hours = (datetime.now(SHANGHAI) - latest_dt).total_seconds() / 3600
            if age_hours >= 48:
                score = max(0, score + factors["sla_aging_48h"])
                why = f"{why}（aging）"
        latest_body = ""
        ctx_path = state_root / "runtime" / "context" / "phase1-context.json"
        sampled = _load_json(ctx_path, {})
        body_map = sampled.get("sampled_bodies", {}) if isinstance(sampled, dict) else {}
        if isinstance(body_map, dict):
            entry = body_map.get(ref) or body_map.get(str(latest.get("id", "")))
            if isinstance(entry, dict):
                latest_body = str(entry.get("body", "") or "")
            elif isinstance(entry, str):
                latest_body = entry
        verbs = _load_action_verbs()
        action_hint = ""
        hay = f"{latest.get('subject', '')} {latest_body}"
        for verb in verbs:
            if verb and verb in hay:
                score += factors["action_verb"]
                action_hint = verb
                break
        from .imap_fetch import is_unread

        unread = sum(1 for _, r in rows if is_unread(r.get("flags") if isinstance(r.get("flags"), list) else []))
        fp = f"{ref}|{','.join(tags)}|{q.get('waiting_on', '')}"
        terms = sorted(set(_extract_tokens(tk) + _extract_tokens(latest.get("subject", ""))))
        snap = ThreadSnapshot(
            thread_key=tk, latest_subject=str(latest.get("subject", "")),
            last_activity_at=latest_dt.isoformat(), latest_message_ref=ref,
            new_message_count=len(in_window), message_count=len(rows),
            unread_count=unread, queue_tags=tags, waiting_on=q.get("waiting_on"),
            deadline=q.get("deadline"),
            why=why, fingerprint=fp, query_terms=terms, score=score,
            recipient_role=aggregate_thread_recipient_role(
                [{"recipient_role": r.get("recipient_role")} for _, r in rows]
            ),
            latest_recipient_role=str(latest.get("recipient_role") or "unknown"),
            action_hint=action_hint,
            evidence_basis=str(q.get("evidence_basis") or ""),
            action_target=str(q.get("action_target") or ""),
            evidence_refs=list(q.get("evidence_refs") or []) if isinstance(q.get("evidence_refs"), list) else None,
            reopened_reason=reopened.get(tk, ""),
        )
        snapshots.append(snap)

    snapshots.sort(key=lambda s: (s.score, s.last_activity_at), reverse=True)
    # Hidden (local complete/dismiss) stay in thread_index for inspect; leave attention/recent.
    visible = [s for s in snapshots if s.thread_key not in hidden_keys]
    recent = [s for s in visible if s.new_message_count > 0][:20]
    attention = [s for s in visible if s.queue_tags][:20]
    misses = _queue_join_diagnostics(state_root, snapshots)

    payload = {
        "generated_at": _now_iso(),
        "window_hours": window_hours,
        "summary": {
            "tracked_threads": len(visible),
            "recent_activity_count": len(recent),
            "needs_attention_count": len(attention),
        },
        "recent_activity": [s.to_dict() for s in recent],
        "needs_attention": [s.to_dict() for s in attention],
        "thread_index": [s.to_dict() for s in snapshots],
        "diagnostics": {"queue_join_misses": misses},
        "score_legend": {
            "recent_window": factors["recent_window"],
            "urgent": factors["urgent"],
            "pending": factors["pending"],
            "sla_risk": factors["sla_risk"],
            "sla_aging_48h": factors["sla_aging_48h"],
            "action_verb": factors["action_verb"],
        },
    }
    try:
        from .case_ledger import drop_closed_from_attention
        payload = drop_closed_from_attention(payload, state_root)
    except Exception as exc:
        diag = payload.setdefault("diagnostics", {})
        if not isinstance(diag, dict):
            diag = {}
            payload["diagnostics"] = diag
        diag["case_ledger_error"] = type(exc).__name__
    try:
        from .classification_store import classification_lineage
        lineage = classification_lineage(state_root)
        if lineage is not None:
            payload["classification_lineage"] = lineage
    except Exception as exc:
        diag = payload.setdefault("diagnostics", {})
        if not isinstance(diag, dict):
            diag = {}
            payload["diagnostics"] = diag
        diag["classification_lineage_error"] = type(exc).__name__
    try:
        from .project import attach_projections
        payload = attach_projections(payload, state_root)
    except Exception as exc:
        diag = payload.setdefault("diagnostics", {})
        if not isinstance(diag, dict):
            diag = {}
            payload["diagnostics"] = diag
        diag["projection_error"] = type(exc).__name__
    return payload


_PULSE_LINEAGE = (
    "generated_at",
    "source_account",
    "stale_analysis",
    "analysis_generated_at",
    "analysis_skipped",
    "analysis_skip_reason",
    "fetch_at",
)


def pulse_path(state_root: Path) -> Path:
    return state_root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"


def pulse_publish_lock(state_root: Path):
    """Per-account exclusive lock for queue rebuild vs sync pulse publish."""
    import fcntl
    from contextlib import contextmanager

    @contextmanager
    def _lock():
        path = pulse_path(state_root).with_name("pulse.publish.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = path.open("a+")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()

    return _lock()


def _copy_lineage(payload: dict[str, Any], prior: dict[str, Any] | None, *, generated_at: str | None) -> dict[str, Any]:
    if isinstance(prior, dict):
        for key in _PULSE_LINEAGE:
            if key in prior:
                payload[key] = prior[key]
    if generated_at:
        payload["generated_at"] = str(generated_at)
    return payload


def commit_activity_pulse(
    state_root: Path,
    *,
    preserve_generated_at: str | None = None,
    preserve_lineage: bool = False,
    extra: dict[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[dict[str, Any], Path]:
    payload = build_activity_pulse(state_root, **kwargs)
    prior = None
    if preserve_lineage or preserve_generated_at:
        loaded = _load_json(pulse_path(state_root), {})
        prior = loaded if isinstance(loaded, dict) else {}
        payload = _copy_lineage(payload, prior, generated_at=preserve_generated_at)
    if extra:
        payload.update(extra)
    out = pulse_path(state_root)
    from .imap_fetch import _write_json
    _write_json(out, payload)
    return payload, out


def write_activity_pulse(
    state_root: Path,
    *,
    preserve_generated_at: str | None = None,
    preserve_lineage: bool = False,
    extra: dict[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[dict[str, Any], Path]:
    with pulse_publish_lock(state_root):
        return commit_activity_pulse(
            state_root,
            preserve_generated_at=preserve_generated_at,
            preserve_lineage=preserve_lineage,
            extra=extra,
            **kwargs,
        )


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
    try:
        from .select import semantic_search
        semantic = semantic_search(q, state_root, limit=limit)
        for item in semantic:
            matches.append((int(item.get("match_score", 0)), item))
        matches.sort(key=lambda p: p[0], reverse=True)
    except Exception:
        pass
    out = []
    seen: set[str] = set()
    for _, item in matches:
        tk = str(item.get("thread_key", ""))
        if tk in seen:
            continue
        seen.add(tk)
        item = _attach_latest_message(item, state_root)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _attach_latest_message(item: dict[str, Any], state_root: Path) -> dict[str, Any]:
    ref = str(item.get("latest_message_ref", "") or "")
    ctx = _load_json(state_root / "runtime" / "context" / "phase1-context.json", {})
    bodies = ctx.get("sampled_bodies", {}) if isinstance(ctx, dict) else {}
    entry = None
    if isinstance(bodies, dict):
        entry = bodies.get(ref) or bodies.get(ref.split("#")[-1])
    if isinstance(entry, dict) and entry.get("body"):
        item["latest_message"] = {
            "ref": ref,
            "body_text": str(entry.get("body", ""))[:2000],
            "decoded_with": entry.get("decoded_with", ""),
        }
    elif isinstance(entry, str) and entry.strip():
        item["latest_message"] = {"ref": ref, "body_text": entry[:2000]}
    else:
        item["body_unavailable"] = True
    return item
