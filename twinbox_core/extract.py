"""Targeted mail extraction — time range + keyword filters, isolated from sync."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from .config import owner_email, resolve_imap_config
from .imap_fetch import _write_json, fetch_by_query

SHANGHAI = ZoneInfo("Asia/Shanghai")

WEEKDAY_MAP = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}


@dataclass
class ExtractCriteria:
    folders: list[str] = field(default_factory=lambda: ["INBOX"])
    since: date | None = None
    until: date | None = None
    subject_contains: list[str] = field(default_factory=list)
    subject_regex: list[str] = field(default_factory=list)
    body_contains: list[str] = field(default_factory=list)
    weekdays: list[int] | None = None  # None = no weekday filter
    from_self: bool | None = None
    bucket: str = "iso_week"  # iso_week | none
    fetch_bodies: bool = True
    profile: str | None = None
    from_hour: int | None = None
    to_hour: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "folders": self.folders,
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
            "subject_contains": self.subject_contains,
            "subject_regex": self.subject_regex,
            "body_contains": self.body_contains,
            "weekdays": self._weekday_labels(),
            "from_self": self.from_self,
            "bucket": self.bucket,
            "fetch_bodies": self.fetch_bodies,
            "from_hour": self.from_hour,
            "to_hour": self.to_hour,
        }

    def _weekday_labels(self) -> list[str] | None:
        if self.weekdays is None:
            return None
        labels = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun"}
        return [labels[d] for d in sorted(self.weekdays)]


def _profiles_path(code_root: Path | None = None) -> Path:
    if code_root and (code_root / "config" / "extract-profiles.yaml").is_file():
        return code_root / "config" / "extract-profiles.yaml"
    # twinbox_core/extract.py -> repo root
    root = Path(__file__).resolve().parents[1]
    return root / "config" / "extract-profiles.yaml"


def load_profiles(code_root: Path | None = None) -> dict[str, Any]:
    path = _profiles_path(code_root)
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_weekdays(raw: list[str] | str | None) -> list[int] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        parts = [p.strip().lower() for p in text.split(",") if p.strip()]
    else:
        parts = [str(p).strip().lower() for p in raw if str(p).strip()]
    if not parts:
        return None
    out: list[int] = []
    for part in parts:
        if part not in WEEKDAY_MAP:
            raise ValueError(f"Unknown weekday: {part}")
        out.append(WEEKDAY_MAP[part])
    return sorted(set(out))


def _parse_date(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    return date.fromisoformat(text[:10])


def merge_criteria(
    base: ExtractCriteria,
    overrides: dict[str, Any],
    *,
    code_root: Path | None = None,
) -> ExtractCriteria:
    """Apply CLI/tool overrides onto profile-resolved criteria."""
    if overrides.get("profile"):
        profiles = load_profiles(code_root)
        name = str(overrides["profile"])
        preset = profiles.get(name)
        if not isinstance(preset, dict):
            raise ValueError(f"Unknown extract profile: {name}")
        base = criteria_from_profile(name, preset, code_root=code_root)

    if overrides.get("folders"):
        base.folders = list(overrides["folders"])
    if overrides.get("since") is not None:
        base.since = _parse_date(overrides["since"])
    if overrides.get("until") is not None:
        base.until = _parse_date(overrides["until"])
    if overrides.get("subject_contains") is not None:
        raw = overrides["subject_contains"]
        if isinstance(raw, str):
            base.subject_contains = [p.strip() for p in raw.split(",") if p.strip()]
        else:
            base.subject_contains = [str(p).strip() for p in raw if str(p).strip()]
    if overrides.get("subject_regex") is not None:
        raw = overrides["subject_regex"]
        if isinstance(raw, str):
            base.subject_regex = [raw] if raw.strip() else []
        else:
            base.subject_regex = [str(p) for p in raw if str(p).strip()]
    if "weekdays" in overrides:
        base.weekdays = _parse_weekdays(overrides["weekdays"])
    if overrides.get("body_contains") is not None:
        raw = overrides["body_contains"]
        if isinstance(raw, str):
            base.body_contains = [p.strip() for p in raw.split(",") if p.strip()]
        else:
            base.body_contains = [str(p).strip() for p in raw if str(p).strip()]
    if overrides.get("from_self") is not None:
        base.from_self = bool(overrides["from_self"])
    if overrides.get("bucket") is not None:
        base.bucket = str(overrides["bucket"])
    if overrides.get("fetch_bodies") is not None:
        base.fetch_bodies = bool(overrides["fetch_bodies"])
    if overrides.get("from_hour") is not None:
        base.from_hour = int(overrides["from_hour"])
    if overrides.get("to_hour") is not None:
        base.to_hour = int(overrides["to_hour"])

    return base


def criteria_from_profile(
    name: str,
    preset: dict[str, Any],
    *,
    code_root: Path | None = None,
) -> ExtractCriteria:
    since_days = int(preset.get("default_since_days", 365) or 365)
    since_default = date.today() - timedelta(days=since_days)
    folders = preset.get("folders", ["INBOX"])
    if not isinstance(folders, list):
        folders = ["INBOX"]
    return ExtractCriteria(
        profile=name,
        folders=[str(f) for f in folders],
        since=since_default,
        subject_contains=[str(x) for x in preset.get("subject_contains", []) if str(x).strip()],
        subject_regex=[str(x) for x in preset.get("subject_regex", []) if str(x).strip()],
        body_contains=[str(x) for x in preset.get("body_contains", []) if str(x).strip()],
        weekdays=_parse_weekdays(preset.get("weekdays")),
        from_self=preset.get("from_self"),
        bucket=str(preset.get("bucket", "iso_week") or "iso_week"),
    )


def _parse_envelope_dt(value: object) -> datetime | None:
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
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)


def _subject_matches(subject: str, criteria: ExtractCriteria) -> bool:
    subj = subject or ""
    if not criteria.subject_contains and not criteria.subject_regex:
        return True
    for needle in criteria.subject_contains:
        if needle and needle in subj:
            return True
    for pattern in criteria.subject_regex:
        try:
            if re.search(pattern, subj, re.IGNORECASE):
                return True
        except re.error:
            continue
    if criteria.subject_contains or criteria.subject_regex:
        return False
    return True


def _body_matches(body: str, criteria: ExtractCriteria) -> bool:
    if not criteria.body_contains:
        return True
    for needle in criteria.body_contains:
        if needle and needle in body:
            return True
    return False


def matches_envelope(env: dict[str, Any], criteria: ExtractCriteria, *, owner: str = "") -> bool:
    """Deterministic filter: date window, weekday, from_self, subject, body."""
    dt = _parse_envelope_dt(env.get("date"))
    if criteria.since and dt:
        if dt.date() < criteria.since:
            return False
    elif criteria.since and not dt:
        return False

    if criteria.until and dt:
        if dt.date() >= criteria.until:
            return False
    elif criteria.until and not dt:
        return False

    if criteria.weekdays is not None:
        if dt is None:
            return False
        if dt.weekday() not in criteria.weekdays:
            return False

    if criteria.from_hour is not None or criteria.to_hour is not None:
        if dt is None:
            return False
        hour = dt.astimezone(SHANGHAI).hour
        start = criteria.from_hour if criteria.from_hour is not None else 0
        end = criteria.to_hour if criteria.to_hour is not None else 24
        if not (start <= hour < end):
            return False

    if criteria.from_self is True:
        owner_norm = owner.strip().lower()
        from_addr = str(env.get("from_addr", "") or "").lower()
        if owner_norm and from_addr != owner_norm:
            return False

    if not _subject_matches(str(env.get("subject", "") or ""), criteria):
        return False

    body = str(env.get("body", "") or "")
    if criteria.body_contains and not _body_matches(body, criteria):
        return False

    return True


def _iso_week_label(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def envelope_to_report(env: dict[str, Any], *, bucket: str) -> dict[str, Any]:
    dt = _parse_envelope_dt(env.get("date"))
    folder = str(env.get("folder", "INBOX") or "INBOX")
    uid = str(env.get("id", "") or "")
    report: dict[str, Any] = {
        "sent_at": dt.isoformat() if dt else str(env.get("date", "") or ""),
        "subject": str(env.get("subject", "") or ""),
        "from_name": str(env.get("from_name", "") or ""),
        "from_addr": str(env.get("from_addr", "") or ""),
        "folder": folder,
        "message_ref": f"{folder}#{uid}",
        "body_text": str(env.get("body", "") or ""),
        "body_truncated": bool(env.get("body_truncated", False)),
        "decoded_with": str(env.get("decoded_with", "") or ""),
        "attachments": env.get("attachments") or [],
        "recipient_role": str(env.get("recipient_role", "") or ""),
    }
    if bucket == "iso_week" and dt:
        report["week_of"] = _iso_week_label(dt)
    return report


def bucket_reports(reports: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    """Attach week_of when mode=iso_week; sort by sent_at desc."""
    if mode == "none":
        return sorted(reports, key=lambda r: str(r.get("sent_at", "")), reverse=True)
    return sorted(reports, key=lambda r: str(r.get("sent_at", "")), reverse=True)


def _query_dir(state_root: Path, query_id: str) -> Path:
    return state_root / "runtime" / "queries" / query_id


def run_extract(
    state_root: Path,
    criteria: ExtractCriteria,
    *,
    code_root: Path | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Run targeted IMAP extract; persist under runtime/queries/."""
    if not criteria.since:
        return {"ok": False, "error": "since date is required (use --since or --profile with default_since_days)"}
    if not criteria.folders:
        return {"ok": False, "error": "at least one folder is required"}

    imap_cfg = resolve_imap_config(account_id)
    if not imap_cfg.get("host") or not imap_cfg.get("login"):
        return {"ok": False, "error": "IMAP not configured. Run setup first."}

    envelopes, folder_errors = fetch_by_query(
        imap_cfg,
        criteria.folders,
        since=criteria.since,
        until=criteria.until,
        fetch_bodies=criteria.fetch_bodies,
        subject_terms=criteria.subject_contains or None,
    )

    if folder_errors and not envelopes:
        return {
            "ok": False,
            "error": "IMAP fetch failed for all folders",
            "folder_errors": folder_errors,
        }

    owner = owner_email() or str(imap_cfg.get("login") or "")
    matched = [e for e in envelopes if matches_envelope(e, criteria, owner=owner)]
    reports = [envelope_to_report(e, bucket=criteria.bucket) for e in matched]
    reports = bucket_reports(reports, criteria.bucket)

    query_id = f"{date.today().isoformat()}-{uuid.uuid4().hex[:8]}"
    payload: dict[str, Any] = {
        "ok": True,
        "query_id": query_id,
        "query": criteria.to_dict(),
        "fetched_count": len(envelopes),
        "matched_count": len(reports),
        "folder_errors": folder_errors or None,
        "reports": reports,
        "result_path": str(_query_dir(state_root, query_id) / "result.json"),
    }
    if folder_errors:
        payload["folder_warnings"] = folder_errors

    out_path = _query_dir(state_root, query_id) / "result.json"
    _write_json(out_path, payload)
    return payload
