"""Append-only case lifecycle ledger for feature 015.

Every observation is one JSON line written in append mode; earlier lines are
never rewritten or deleted.  A current view re-derives, per ``(case_ref,
attribute)``, the line with the latest ``valid_from``.  This module deliberately
holds no business stage names: the four default states are the only bare state
words here, and richer stage sets come from a pack lifecycle or analysis rows.
"""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .classification_store import case_ref as _identity_case_ref
from .pulse import normalize_thread_key

DEFAULT_ATTRIBUTE = "lifecycle_state"
DEFAULT_STATES = ("open", "waiting_on_me", "waiting_on_others", "closed")
REOPEN_STATES = ("open",)
CLOSED_VALUE = "closed"
STATUS_VALID = "valid"
STATUS_NEEDS_CONFIRMATION = "needs_confirmation"
_OWNER_WAIT = {"me", "我", "mailbox_owner"}


class LedgerError(ValueError):
    """Stable, non-sensitive rejection reason."""


def case_ledger_path(state_root: Path) -> Path:
    return Path(state_root) / "runtime" / "context" / "case-ledger.jsonl"


def case_ref(scope_id: str, case_key: str) -> str:
    """Stable case identity, shared with the classification store."""
    return _identity_case_ref(scope_id, case_key)


def _scope_id(state_root: Path) -> str:
    return str(Path(state_root).name or "local")


def _load_json(path: Path, default: object) -> object:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _load_yaml_rows(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = data.get(key) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def load_records(state_root: Path) -> list[dict[str, Any]]:
    """Return every parsed ledger line, in append order."""
    path = case_ledger_path(state_root)
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        raise LedgerError("ledger_unreadable") from None
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            raise LedgerError("ledger_corrupt") from None
        if not isinstance(record, dict):
            raise LedgerError("ledger_corrupt")
        records.append(record)
    return records


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _key_of(record: dict[str, Any]) -> tuple[datetime, datetime]:
    return (
        _parse_dt(record.get("valid_from")) or datetime.min.replace(tzinfo=timezone.utc),
        _parse_dt(record.get("recorded_at")) or datetime.min.replace(tzinfo=timezone.utc),
    )


def _declared_states(state_root: Path) -> tuple[str, ...] | None:
    try:
        from .pack import load_active_pack
        pack = load_active_pack(state_root)
    except Exception:
        return None
    if not isinstance(pack, dict):
        return None
    lifecycles = pack.get("lifecycles")
    if not isinstance(lifecycles, dict):
        return None
    states: list[str] = []
    for entry in lifecycles.values():
        if not isinstance(entry, dict):
            continue
        declared = entry.get("states")
        if isinstance(declared, list):
            for value in declared:
                if value:
                    states.append(str(value))
            if states:
                return tuple(dict.fromkeys(states))
    return None


def legal_states(state_root: Path) -> tuple[str, ...]:
    declared = _declared_states(state_root)
    return declared if declared else DEFAULT_STATES


def _declared_reopen(state_root: Path) -> tuple[str, ...] | None:
    try:
        from .pack import load_active_pack
        pack = load_active_pack(state_root)
    except Exception:
        return None
    if not isinstance(pack, dict):
        return None
    lifecycles = pack.get("lifecycles")
    if not isinstance(lifecycles, dict):
        return None
    for entry in lifecycles.values():
        if not isinstance(entry, dict):
            continue
        reopen = entry.get("reopen")
        if isinstance(reopen, list):
            values = tuple(str(v) for v in reopen if v)
            if values:
                return values
        if isinstance(reopen, str) and reopen:
            return (reopen,)
    return None


def reopen_states(state_root: Path) -> tuple[str, ...]:
    return _declared_reopen(state_root) or REOPEN_STATES


def _append_line(state_root: Path, record: dict[str, Any]) -> None:
    path = case_ledger_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name("case-ledger.lock")
    with lock_path.open("a+", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def append_record(
    state_root: Path,
    *,
    case_ref: str,
    attribute: str,
    value: str,
    valid_from: str,
    evidence_ref: str | None = None,
    source: str | None = None,
    recorded_at: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and append one observation. Existing lines are never touched."""
    if not case_ref or not attribute:
        raise LedgerError("ledger_identity_invalid")
    value = str(value)
    recorded_at = recorded_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    states = legal_states(state_root)
    reopen = reopen_states(state_root)
    prior = current_view(state_root).get((case_ref, attribute))

    status = STATUS_VALID
    if value not in states:
        status = STATUS_NEEDS_CONFIRMATION
    elif prior is not None and prior.get("value") == CLOSED_VALUE and value not in reopen:
        status = STATUS_NEEDS_CONFIRMATION

    record: dict[str, Any] = {
        "case_ref": case_ref,
        "attribute": attribute,
        "value": value,
        "valid_from": str(valid_from),
        "recorded_at": recorded_at,
        "evidence_ref": evidence_ref,
        "source": source or "manual",
        "status": status,
    }
    if extra:
        for key, item in extra.items():
            if item is not None:
                record[str(key)] = item
    _append_line(state_root, record)
    return dict(record)


def current_view(state_root: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Return the latest-valid line per (case_ref, attribute).

    ``needs_confirmation`` lines are skipped, so they never become current.  A
    later append carrying an older ``valid_from`` (backfill) cannot win because
    the newest ``valid_from`` is selected.
    """
    view: dict[tuple[str, str], dict[str, Any]] = {}
    for record in load_records(state_root):
        if record.get("status") == STATUS_NEEDS_CONFIRMATION:
            continue
        key = (str(record.get("case_ref") or ""), str(record.get("attribute") or ""))
        if not key[0] or not key[1]:
            continue
        existing = view.get(key)
        if existing is None or _key_of(record) > _key_of(existing):
            view[key] = dict(record)
    return view


def current_value(state_root: Path, case_ref: str, attribute: str) -> str | None:
    record = current_view(state_root).get((case_ref, attribute))
    return record.get("value") if record else None


def _analysis_rows(state_root: Path) -> dict[str, list[dict[str, Any]]]:
    phase4 = Path(state_root) / "runtime" / "validation" / "phase-4"
    out: dict[str, list[dict[str, Any]]] = {}
    for filename, key in (
        ("daily-urgent.yaml", "daily_urgent"),
        ("pending-replies.yaml", "pending_replies"),
        ("sla-risks.yaml", "sla_risks"),
    ):
        for row in _load_yaml_rows(phase4 / filename, key):
            tk = str(row.get("thread_key") or "").strip()
            if not tk:
                continue
            out.setdefault(tk, []).append(row)
    return out


def _envelopes_by_thread(state_root: Path) -> dict[str, list[dict[str, Any]]]:
    raw = Path(state_root) / "runtime" / "validation" / "phase-1" / "raw" / "envelopes-merged.json"
    rows = _load_json(raw, [])
    ctx = Path(state_root) / "runtime" / "context" / "phase1-context.json"
    data = _load_json(ctx, {})
    if isinstance(data, dict):
        rows = data.get("envelopes", rows)
    envelopes = [r for r in rows if isinstance(r, dict)]
    by_thread: dict[str, list[dict[str, Any]]] = {}
    for env in envelopes:
        by_thread.setdefault(normalize_thread_key(env.get("subject")), []).append(env)
    return by_thread


def _latest_mail(rows: list[dict[str, Any]]) -> tuple[str, str | None]:
    """Latest envelope for a thread: (valid_from ISO, evidence_ref)."""
    if not rows:
        return "", None
    latest = max(rows, key=lambda row: _parse_dt(row.get("date")) or datetime.min.replace(tzinfo=timezone.utc))
    when = latest.get("date")
    ref = f"{latest.get('folder', 'INBOX')}#{latest.get('id', '')}" if latest.get("id") else None
    return (str(when) if when else ""), ref


def _is_valid_newest_reopen(envelopes: list[dict[str, Any]]) -> bool:
    """True when the newest envelope is a valid reopen per pulse's reopen rule."""
    if not envelopes:
        return False
    latest = max(
        envelopes,
        key=lambda env: _parse_dt(env.get("date")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    from .pulse import _is_valid_reopen
    from .config import owner_email
    try:
        owner = owner_email()
    except Exception:
        owner = ""
    return _is_valid_reopen(latest, owner)


def _infer_state(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        if row.get("resolved_by_reply"):
            return CLOSED_VALUE
    for row in rows:
        if row.get("waiting_on_me") is True:
            return "waiting_on_me"
    for row in rows:
        waiting = str(row.get("waiting_on") or "").strip().lower()
        if waiting and waiting not in _OWNER_WAIT:
            return "waiting_on_others"
        if row.get("action_target"):
            return "waiting_on_others"
        if row.get("waiting_on_me") is False and waiting:
            return "waiting_on_others"
    return "open"


def _first_field(rows: list[dict[str, Any]], key: str) -> Any:
    for row in rows:
        if row.get(key) is not None:
            return row.get(key)
    return None


def derive_case_states(
    state_root: Path, *, scope_id: str | None = None, attribute: str | None = None,
) -> list[dict[str, Any]]:
    """Derive candidate state records from existing analysis rows only."""
    scope_id = scope_id or _scope_id(state_root)
    attribute = attribute or DEFAULT_ATTRIBUTE
    rows_by_tk = _analysis_rows(state_root)
    envelopes_by_tk = _envelopes_by_thread(state_root)
    view = current_view(state_root)
    records: list[dict[str, Any]] = []
    for tk, rows in rows_by_tk.items():
        value = _infer_state(rows)
        prior = view.get((case_ref(scope_id, tk), attribute))
        # A once-closed case is durable across window rewrites: it may only
        # reopen when the newest mail is a valid reopen, otherwise closed sticks.
        if (prior is not None and prior.get("value") == CLOSED_VALUE
                and value != CLOSED_VALUE
                and not _is_valid_newest_reopen(envelopes_by_tk.get(tk, []))):
            continue
        valid_from, evidence_ref = _latest_mail(envelopes_by_tk.get(tk, []))
        record: dict[str, Any] = {
            "case_ref": case_ref(scope_id, tk),
            "attribute": attribute,
            "value": value,
            "valid_from": valid_from,
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "evidence_ref": evidence_ref,
            "source": "analysis_derived",
            "status": STATUS_VALID,
        }
        for field in ("stage_proposals", "followup"):
            val = _first_field(rows, field)
            if val is not None:
                record[field] = val
        records.append(record)
    return records


def sync_derived_states(
    state_root: Path, *, scope_id: str | None = None, attribute: str | None = None,
) -> list[dict[str, Any]]:
    """Append a derived record only when it changes the current value."""
    scope_id = scope_id or _scope_id(state_root)
    attribute = attribute or DEFAULT_ATTRIBUTE
    view = current_view(state_root)
    appended: list[dict[str, Any]] = []
    for candidate in derive_case_states(state_root, scope_id=scope_id, attribute=attribute):
        prior = view.get((candidate["case_ref"], candidate["attribute"]))
        if prior is not None and prior.get("value") == candidate["value"]:
            continue
        extra = {
            field: candidate[field]
            for field in ("stage_proposals", "followup")
            if field in candidate
        }
        record = append_record(
            state_root,
            case_ref=candidate["case_ref"],
            attribute=candidate["attribute"],
            value=candidate["value"],
            valid_from=candidate["valid_from"] or _now_iso(),
            evidence_ref=candidate.get("evidence_ref"),
            source=candidate["source"],
            extra=extra,
        )
        appended.append(record)
        view[(candidate["case_ref"], candidate["attribute"])] = record
    return appended


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _closed_thread_keys(
    state_root: Path, thread_keys: Iterable[str], *, scope_id: str, attribute: str,
) -> set[str]:
    view = current_view(state_root)
    closed: set[str] = set()
    for tk in thread_keys:
        if not tk:
            continue
        record = view.get((case_ref(scope_id, tk), attribute))
        if record and record.get("value") == CLOSED_VALUE:
            closed.add(tk)
    return closed


def drop_closed_from_attention(
    payload: dict[str, Any],
    state_root: Path,
    *,
    scope_id: str | None = None,
    attribute: str | None = None,
) -> dict[str, Any]:
    """Remove ``closed`` threads from pulse ``needs_attention``; keep them visible."""
    scope_id = scope_id or _scope_id(state_root)
    attribute = attribute or DEFAULT_ATTRIBUTE
    thread_keys: set[str] = set()
    for key in ("thread_index", "needs_attention"):
        rows = payload.get(key)
        if isinstance(rows, list):
            thread_keys |= {str(item.get("thread_key") or "") for item in rows if isinstance(item, dict)}
    closed = _closed_thread_keys(state_root, thread_keys, scope_id=scope_id, attribute=attribute)
    if not closed:
        return payload
    attention = payload.get("needs_attention")
    if isinstance(attention, list):
        filtered = [item for item in attention if str(item.get("thread_key") or "") not in closed]
        payload["needs_attention"] = filtered
        summary = payload.get("summary")
        if isinstance(summary, dict):
            summary["needs_attention_count"] = len(filtered)
    return payload
