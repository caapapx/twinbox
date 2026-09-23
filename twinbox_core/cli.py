"""Twinbox Lite CLI — lightweight entry point for OpenClaw skill.

Usage: python3 -m twinbox_core.cli <command> [--json]

Commands:
  setup        — Validate IMAP + import LLM from OpenClaw
  sync         — Fetch mail + run LLM analysis (--job daytime-sync | nightly-full | quick-refresh)
  latest-mail  — Latest mail / activity pulse snapshot
  todo         — Urgent / pending queue
  weekly       — Weekly brief
  thread       — Inspect or search threads
  extract      — Targeted IMAP extract by date range + keywords (isolated from sync)
  queue        — Mark thread complete / dismiss / restore
  status       — Mailbox health + setup status
  schedule     — run-due jobs under file lock
  realtime-watch — externally supervised IMAP IDLE/poll trigger (quick-refresh only)
  onboard      — write user semantic pack from questionnaire answers
  taxonomy     — induce / confirm / drift for pack taxonomy drafts
  material-import — optional xlsx/docx pack fragment
  actions      — dry-run proposals / review
  semantics    — dynamic classification catalog/case projections
  feedback     — authorized correction/confirmation/execution receipt
  weknora     — local diagnostics / gated sync / revoke (hide then delete)
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import get_weknora_config

SHANGHAI = ZoneInfo("Asia/Shanghai")
STALE_HOURS_DEFAULT = 4


def _state_root() -> Path:
    from .config import state_root
    return state_root()


def _parse_flag(args: list[str], name: str) -> tuple[str | None, list[str]]:
    """Extract --name VALUE from args; return (value, remaining)."""
    out: list[str] = []
    value: str | None = None
    i = 0
    while i < len(args):
        if args[i] == name and i + 1 < len(args):
            value = args[i + 1]
            i += 2
            continue
        out.append(args[i])
        i += 1
    return value, out


def _account_root(account_id: str | None = None) -> Path:
    from .config import account_state_root
    return account_state_root(account_id)


def _resolved_account_id(account_id: str | None = None) -> str:
    from .config import default_account_id
    aid = (account_id or default_account_id() or "").strip()
    return aid or "default"


def _json_out(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _envelope_id_set(account_root: Path) -> set[tuple[str, str]]:
    path = account_root / "runtime" / "context" / "phase1-context.json"
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    envelopes = data.get("envelopes") if isinstance(data, dict) else None
    if not isinstance(envelopes, list):
        return set()
    out: set[tuple[str, str]] = set()
    for env in envelopes:
        if not isinstance(env, dict):
            continue
        uid = str(env.get("id", "") or "")
        if not uid:
            continue
        out.add((str(env.get("folder", "INBOX") or "INBOX"), uid))
    return out


def _id_pair_set(raw: object) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        uid = str(item[1] or "")
        if not uid:
            continue
        out.add((str(item[0] or "INBOX"), uid))
    return out


def _pending_path(account_root: Path) -> Path:
    return account_root / "runtime" / "context" / "pending-analysis.json"


def _load_pending(account_root: Path) -> tuple[set[tuple[str, str]], dict[str, int]]:
    path = _pending_path(account_root)
    if not path.is_file():
        return set(), {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set(), {}
    if not isinstance(data, dict):
        return set(), {}
    uv: dict[str, int] = {}
    raw_uv = data.get("uidvalidity")
    if isinstance(raw_uv, dict):
        for folder, val in raw_uv.items():
            try:
                uv[str(folder)] = int(val or 0)
            except (TypeError, ValueError):
                continue
    return _id_pair_set(data.get("ids")), uv


def _save_pending(
    account_root: Path,
    ids: set[tuple[str, str]],
    uidvalidity: dict[str, int],
) -> None:
    from .imap_fetch import _write_json
    payload = {
        "ids": sorted([list(item) for item in ids]),
        "uidvalidity": uidvalidity,
    }
    _write_json(_pending_path(account_root), payload)


def _watermark_uidvalidity(account_root: Path) -> dict[str, int]:
    from .imap_fetch import _load_json, _watermarks_path
    raw = _load_json(_watermarks_path(account_root), {})
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for folder, row in raw.items():
        if not isinstance(row, dict):
            continue
        try:
            out[str(folder)] = int(row.get("uidvalidity") or 0)
        except (TypeError, ValueError):
            continue
    return out


def _reconcile_pending_uv(
    ids: set[tuple[str, str]],
    pending_uv: dict[str, int],
    watermark_uv: dict[str, int],
) -> tuple[set[tuple[str, str]], dict[str, int]]:
    kept = set(ids)
    uv = dict(pending_uv)
    for folder, current in watermark_uv.items():
        prev = int(uv.get(folder) or 0)
        if prev and current and prev != current:
            kept = {item for item in kept if item[0] != folder}
        if current:
            uv[folder] = current
    return kept, uv


def _recovery_hint(tool: str, msg: str) -> dict[str, Any]:
    return {"ok": False, "recovery_tool": tool, "error": msg}


# --- Commands ---

def cmd_setup() -> dict[str, Any]:
    from .config import resolve_imap_config, setup_from_env
    from .imap_fetch import preflight

    result = setup_from_env()
    imap_cfg = resolve_imap_config()
    pf = preflight(imap_cfg)
    result["preflight"] = pf

    # Also validate LLM
    from .llm import validate_backend
    llm_ok, llm_err = validate_backend()
    result["llm_validate"] = {"ok": llm_ok}
    if not llm_ok:
        result["llm_validate"]["error"] = llm_err

    return result



def cmd_sync(job: str = "daytime-sync", account_id: str | None = None) -> dict[str, Any]:
    from .config import resolve_imap_config, default_account_id, list_accounts
    from .imap_fetch import fetch_incremental
    from .analyze import run_analysis
    from .pulse import write_activity_pulse
    from .runs import append_run, classify_error, new_run_id

    # Multi-account fan-out: explicit account_id syncs one; omit syncs all registered
    # accounts with per-account failure isolation (one failure must not stop others).
    if account_id is None:
        accounts = list_accounts()
        if len(accounts) > 1:
            results = []
            for row in accounts:
                aid_one = str(row.get("account_id") or "default")
                try:
                    results.append(cmd_sync(job, account_id=aid_one))
                except Exception as exc:
                    results.append({"ok": False, "account_id": aid_one, "error": str(exc)})
            any_ok = any(bool(r.get("ok")) for r in results)
            return {
                "ok": any_ok,
                "job": job,
                "multi_account": True,
                "accounts": results,
                "count": len(results),
                "failed": [r.get("account_id") for r in results if not r.get("ok")],
            }

    aid = (account_id or default_account_id()).strip() or "default"
    root = _account_root(aid)
    run_id = new_run_id()
    attempted_at = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    imap_cfg = resolve_imap_config(aid)
    if not imap_cfg.get("host") or not imap_cfg.get("login"):
        err = {"ok": False, "error": "IMAP not configured. Run setup first.", "account_id": aid, "run_id": run_id}
        append_run(
            root,
            {
                "run_id": run_id,
                "account_id": aid,
                "job": job,
                "ok": False,
                "attempted_at": attempted_at,
                "error_class": "imap_connect",
                "error": err["error"],
            },
        )
        return err

    folders = ["INBOX"]
    lookback = 30 if job == "nightly-full" else 7
    # quick-refresh: fetch + embed + rebuild pulse, keep the last scheduled LLM analysis.
    quick = job == "quick-refresh"
    prior_ids = _envelope_id_set(root)

    fetch_started = time.monotonic()
    fetch_result = fetch_incremental(
        root, folders, imap_cfg,
        sample_body_count=30, lookback_days=lookback,
        account_id=aid,
    )
    if fetch_result.get("status") == "error":
        msg = str(fetch_result.get("error") or "").strip()
        folder_errors = fetch_result.get("folder_errors")
        if not msg and isinstance(folder_errors, list) and folder_errors:
            bits = []
            for err in folder_errors[:3]:
                if not isinstance(err, dict):
                    continue
                bits.append(
                    f"{err.get('folder') or '?'}:{err.get('step') or '?'}:{err.get('detail') or 'error'}"
                )
            msg = "; ".join(bits)
        msg = msg or "fetch failed"
        err_class = classify_error(step="fetch", message=msg)
        out = {"ok": False, "step": "fetch", "account_id": aid, "run_id": run_id, **fetch_result}
        append_run(
            root,
            {
                "run_id": run_id,
                "account_id": aid,
                "job": job,
                "ok": False,
                "attempted_at": attempted_at,
                "error_class": err_class,
                "error": msg,
                "stages": {"fetch": "error"},
            },
        )
        return out
    fetch_ms = round((time.monotonic() - fetch_started) * 1000)
    new_count = fetch_result.get("new_envelope_count")
    reported = fetch_result.get("new_envelope_ids")
    if isinstance(reported, list):
        # Prefer IMAP-new ids that survived into context; subtract prior so duplicates → empty.
        current = _envelope_id_set(root)
        new_ids: set[tuple[str, str]] = set()
        for item in reported:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            key = (str(item[0] or "INBOX"), str(item[1] or ""))
            if key[1] and key in current and key not in prior_ids:
                new_ids.add(key)
    else:
        new_ids = _envelope_id_set(root) - prior_ids
    current_ids = _envelope_id_set(root)
    pending_ids, pending_uv = _load_pending(root)
    pending_ids, pending_uv = _reconcile_pending_uv(
        pending_ids, pending_uv, _watermark_uidvalidity(root),
    )
    pending_ids |= new_ids
    pending_ids &= current_ids
    _save_pending(root, pending_ids, pending_uv)
    urgent_yaml = root / "runtime" / "validation" / "phase-4" / "daily-urgent.yaml"
    has_analysis = urgent_yaml.is_file()

    degraded: list[str] = []
    # Quick refresh is explicitly a local pulse rebuild; it must not make a
    # network-only Sent-header attempt part of its health result.
    if not quick:
        try:
            from .imap_fetch import capture_sent_headers
            sent = capture_sent_headers(root, imap_cfg, lookback_days=max(lookback, 30))
            if not sent.get("ok"):
                degraded.append("sent_headers")
        except Exception:
            degraded.append("sent_headers")
    analysis_started = time.monotonic()
    analysis_path = "full"
    if quick:
        analysis: dict[str, Any] = {"ok": True, "skipped": True, "reason": "quick-refresh"}
        analysis_path = "quick"
    elif job == "nightly-full" or not has_analysis or new_count is None:
        analysis = run_analysis(root)
        analysis_path = "full"
        if not analysis.get("ok"):
            degraded.append("analysis")
        elif not analysis.get("skipped"):
            pending_ids -= _id_pair_set(analysis.get("analyzed_ids"))
    elif pending_ids:
        analysis = run_analysis(root, only_ids=set(pending_ids))
        analysis_path = "incremental"
        if not analysis.get("ok"):
            degraded.append("analysis")
        elif not analysis.get("skipped"):
            pending_ids -= _id_pair_set(analysis.get("analyzed_ids"))
    else:
        # True noop, or IMAP count>0 but no new ids in window (duplicate UID / trimmed).
        # R8 zjma12: new_envelope_count=1 + empty new_ids used to fall into full — never again.
        reason = "no-new-mail" if int(new_count or 0) == 0 else "no-new-ids-in-window"
        analysis = {"ok": True, "skipped": True, "reason": reason}
        analysis_path = "skip"
    _save_pending(root, pending_ids, pending_uv)
    analysis_ms = round((time.monotonic() - analysis_started) * 1000)

    pulse_started = time.monotonic()
    try:
        from .pulse import _load_yaml
        extra: dict[str, Any] = {
            "source_account": aid,
            "fetch_at": fetch_result.get("generated_at") or "",
        }
        extra["analysis_generated_at"] = _load_yaml(urgent_yaml).get("generated_at") or None
        if quick:
            extra["analysis_skipped"] = True
        if analysis.get("skipped"):
            extra["analysis_skipped"] = True
            extra["analysis_skip_reason"] = analysis.get("reason")
        if "analysis" in degraded:
            extra["stale_analysis"] = True
        pulse_data, pulse_path = write_activity_pulse(root, extra=extra)
        pulse_data.update(extra)
        pulse_ok = True
    except Exception as exc:
        pulse_ok = False
        pulse_data = {"error": str(exc)}
        degraded.append("pulse")

    pulse_ms = round((time.monotonic() - pulse_started) * 1000)
    fetch_at = fetch_result.get("generated_at") or ""
    timings = {
        "fetch_ms": fetch_ms,
        "analysis_ms": analysis_ms,
        "pulse_ms": pulse_ms,
        **(fetch_result.get("timings_ms") if isinstance(fetch_result.get("timings_ms"), dict) else {}),
    }
    ok = True
    error_class = None
    error_msg = None
    if not pulse_ok:
        ok = False
        error_class = classify_error(step="pulse", message=str(pulse_data.get("error") or ""))
        error_msg = str(pulse_data.get("error") or "pulse failed")
    elif "analysis" in degraded:
        error_class = classify_error(step="analysis", message=str(analysis.get("error") or ""), degraded=degraded)
        error_msg = str(analysis.get("error") or "analysis degraded")

    append_run(
        root,
        {
            "run_id": run_id,
            "account_id": aid,
            "job": job,
            "ok": ok and not (degraded and not pulse_ok),
            "attempted_at": attempted_at,
            "degraded": degraded,
            "error_class": error_class,
            "error": error_msg,
            "timings_ms": timings,
            "stages": {
                "fetch": "ok",
                "analysis": "skipped" if analysis.get("skipped") else ("degraded" if "analysis" in degraded else "ok"),
                "pulse": "ok" if pulse_ok else "error",
            },
            "select": analysis.get("select") if isinstance(analysis.get("select"), dict) else None,
            "analysis_path": analysis_path,
            "new_envelope_count": new_count,
            "pending_analysis_count": len(pending_ids),
        },
    )

    return {
        "ok": True if pulse_ok else False,
        "job": job,
        "account_id": aid,
        "run_id": run_id,
        "source_account": aid,
        "degraded": degraded,
        "analysis_path": analysis_path,
        "pending_analysis_count": len(pending_ids),
        "fetch": fetch_result,
        "analysis": analysis,
        "pulse": {"ok": pulse_ok, "tracked_threads": pulse_data.get("summary", {}).get("tracked_threads", 0)},
        "consistency": {
            "fetch_at": fetch_at,
            "analysis_ok": analysis.get("ok"),
            "analysis_skipped": bool(analysis.get("skipped")),
            "analysis_path": analysis_path,
            "analysis_generated_at": pulse_data.get("analysis_generated_at"),
            "pulse_ok": pulse_ok,
        },
        "watermark_range": fetch_result.get("watermark_range"),
        "timings_ms": timings,
    }



def _staleness(generated_at: str, *, threshold_hours: int = STALE_HOURS_DEFAULT) -> dict[str, Any]:
    parsed = None
    if generated_at:
        try:
            parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    if parsed is None:
        return {"stale": True, "age_hours": None, "threshold_hours": threshold_hours}
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    age = (datetime.now(SHANGHAI) - parsed.astimezone(SHANGHAI)).total_seconds() / 3600
    return {"stale": age >= threshold_hours, "age_hours": round(age, 2), "threshold_hours": threshold_hours}


_CARD_KEYS = (
    "thread_key",
    "latest_subject",
    "last_activity_at",
    "latest_message_ref",
    "unread_count",
    "new_message_count",
    "message_count",
    "queue_tags",
    "why",
    "score",
    "projection",
    "action_hint",
    "waiting_on",
    "recipient_role",
    "latest_recipient_role",
    "evidence_basis",
    "action_target",
    "reopened_reason",
)


def _compact_thread(row: object) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    card = {key: row[key] for key in _CARD_KEYS if key in row and row[key] not in (None, "", [])}
    return card or None


def _compact_rows(rows: object, *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        card = _compact_thread(row)
        if card:
            out.append(card)
        if len(out) >= limit:
            break
    return out


def cmd_latest_mail(unread_only: bool = False, account_id: str | None = None) -> dict[str, Any]:
    from .pulse import hidden_thread_keys, load_activity_pulse
    root = _account_root(account_id)
    try:
        pulse = load_activity_pulse(root)
    except RuntimeError:
        return _recovery_hint("twinbox_sync", "Missing activity-pulse.json")

    hidden = hidden_thread_keys(root)
    threads = [
        t for t in pulse.get("thread_index", [])
        if isinstance(t, dict) and str(t.get("thread_key", "")) not in hidden
    ]
    if unread_only:
        threads = [t for t in threads if t.get("unread_count", 0) > 0]
    threads.sort(key=lambda t: str(t.get("last_activity_at") or ""), reverse=True)
    cards = _compact_rows(threads, limit=5)

    return {
        "ok": True,
        "source_account": _resolved_account_id(account_id),
        "generated_at": pulse.get("generated_at", ""),
        "staleness": _staleness(str(pulse.get("generated_at", "") or "")),
        "summary": pulse.get("summary", {}),
        "latest": cards[0] if cards else None,
        "threads": cards,
    }


def cmd_todo(account_id: str | None = None) -> dict[str, Any]:
    from .pulse import hidden_thread_keys, load_activity_pulse
    root = _account_root(account_id)
    try:
        pulse = load_activity_pulse(root)
    except RuntimeError:
        return _recovery_hint("twinbox_sync", "Missing activity-pulse.json")

    hidden = hidden_thread_keys(root)

    def _visible(rows: object) -> list[dict[str, Any]]:
        if not isinstance(rows, list):
            return []
        return [
            r for r in rows
            if isinstance(r, dict) and str(r.get("thread_key", "")) not in hidden
        ]

    attention = _compact_rows(_visible(pulse.get("needs_attention", [])), limit=20)
    raw_proj = pulse.get("projections")
    projections: dict[str, Any] = {}
    if isinstance(raw_proj, dict):
        for key, rows in raw_proj.items():
            projections[key] = _compact_rows(_visible(rows), limit=8)
    return {
        "ok": True,
        "source_account": _resolved_account_id(account_id),
        "generated_at": pulse.get("generated_at", ""),
        "staleness": _staleness(str(pulse.get("generated_at", "") or "")),
        "needs_attention": attention,
        "projections": projections,
        "count": len(attention),
    }


def cmd_weekly(account_id: str | None = None) -> dict[str, Any]:
    root = _account_root(account_id)
    path = root / "runtime" / "validation" / "phase-4" / "weekly-brief-raw.json"
    if not path.is_file():
        return _recovery_hint("twinbox_sync", "Missing weekly-brief-raw.json. Run sync with job=nightly-full.")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "staleness": _staleness(str(data.get("generated_at", "") or "")),
        **data,
        "source_account": _resolved_account_id(account_id),
    }


def cmd_thread_inspect(query: str, account_id: str | None = None) -> dict[str, Any]:
    from .pulse import search_threads
    root = _account_root(account_id)
    try:
        results = search_threads(query, root, limit=10)
    except RuntimeError:
        return _recovery_hint("twinbox_sync", "Missing activity-pulse.json")
    return {
        "ok": True,
        "source_account": _resolved_account_id(account_id),
        "query": query,
        "results": results,
        "count": len(results),
    }


def _code_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _parse_extract_args(remaining: list[str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    i = 0
    while i < len(remaining):
        arg = remaining[i]
        if arg == "--profile" and i + 1 < len(remaining):
            overrides["profile"] = remaining[i + 1]
            i += 2
        elif arg == "--since" and i + 1 < len(remaining):
            overrides["since"] = remaining[i + 1]
            i += 2
        elif arg == "--until" and i + 1 < len(remaining):
            overrides["until"] = remaining[i + 1]
            i += 2
        elif arg == "--folder":
            overrides.setdefault("folders", [])
            if i + 1 < len(remaining):
                overrides["folders"].append(remaining[i + 1])
            i += 2
        elif arg == "--subject-contains" and i + 1 < len(remaining):
            overrides["subject_contains"] = remaining[i + 1]
            i += 2
        elif arg == "--subject-regex":
            overrides.setdefault("subject_regex", [])
            if i + 1 < len(remaining):
                overrides["subject_regex"].append(remaining[i + 1])
            i += 2
        elif arg == "--body-contains" and i + 1 < len(remaining):
            overrides["body_contains"] = remaining[i + 1]
            i += 2
        elif arg == "--weekdays" and i + 1 < len(remaining):
            overrides["weekdays"] = remaining[i + 1]
            i += 2
        elif arg == "--bucket" and i + 1 < len(remaining):
            overrides["bucket"] = remaining[i + 1]
            i += 2
        elif arg == "--from-self":
            overrides["from_self"] = True
            i += 1
        elif arg == "--no-body":
            overrides["fetch_bodies"] = False
            i += 1
        elif arg == "--from-hour" and i + 1 < len(remaining):
            overrides["from_hour"] = remaining[i + 1]
            i += 2
        elif arg == "--to-hour" and i + 1 < len(remaining):
            overrides["to_hour"] = remaining[i + 1]
            i += 2
        elif arg == "--source" and i + 1 < len(remaining):
            overrides["source"] = remaining[i + 1]
            i += 2
        else:
            i += 1
    return overrides


def cmd_extract(remaining: list[str], account_id: str | None = None) -> dict[str, Any]:
    from .extract import ExtractCriteria, merge_criteria, run_extract

    overrides = _parse_extract_args(remaining)
    base = ExtractCriteria()
    try:
        criteria = merge_criteria(base, overrides, code_root=_code_root())
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    if not criteria.since and not overrides.get("profile"):
        return {
            "ok": False,
            "error": "Provide --since YYYY-MM-DD or --profile <name> (e.g. weekly_report)",
        }

    return run_extract(_account_root(account_id), criteria, code_root=_code_root(), account_id=account_id)


def cmd_queue_action(action: str, thread_key: str, reason: str = "", account_id: str | None = None) -> dict[str, Any]:
    from .pulse import commit_activity_pulse, pulse_publish_lock
    from .queue import complete_thread, dismiss_thread, restore_thread
    root = _account_root(account_id)
    with pulse_publish_lock(root):
        if action == "complete":
            result = complete_thread(root, thread_key, reason or "已完成")
        elif action == "dismiss":
            result = dismiss_thread(root, thread_key, reason or "已处理")
        elif action == "restore":
            result = restore_thread(root, thread_key)
        else:
            return {"ok": False, "error": f"Unknown action: {action}"}

        if not result.get("ok"):
            return result

        try:
            commit_activity_pulse(root, preserve_lineage=True)
            return {**result, "pulse_updated": True}
        except Exception as exc:
            return {
                **result,
                "pulse_updated": False,
                "pulse_error": type(exc).__name__,
            }



def status_warnings(last: dict[str, Any] | None, misses: list, join_misses: list) -> list:
    warnings = []
    select = {}
    if isinstance(last, dict) and isinstance(last.get("select"), dict):
        select = last["select"]
    if select.get("embeddings_degraded"):
        warnings.append({"embeddings_degraded": True, "run_id": last.get("run_id") if isinstance(last, dict) else None})
    if misses:
        warnings.append({"missed_runs": misses})
    if join_misses:
        warnings.append({"queue_join_misses": join_misses})
    return warnings


def cmd_status(account_id: str | None = None) -> dict[str, Any]:
    from .config import resolve_imap_config, list_accounts, default_account_id
    from .imap_fetch import preflight
    from .llm import validate_backend
    from .runs import account_freshness, load_last_run, load_recent_runs

    aid = (account_id or default_account_id()).strip() or "default"
    root = _account_root(aid)
    imap_cfg = resolve_imap_config(aid)
    pf = preflight(imap_cfg)

    llm_ok, llm_err = validate_backend()

    pulse_path = root / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
    context_path = root / "runtime" / "context" / "phase1-context.json"
    analysis_path = root / "runtime" / "validation" / "phase-4" / "pending-replies.yaml"
    pulse_exists = pulse_path.is_file()
    context_exists = context_path.is_file()

    def _mtime_iso(path):
        if not path.is_file():
            return None
        return datetime.fromtimestamp(path.stat().st_mtime, tz=SHANGHAI).isoformat(timespec="seconds")

    from .schedule import missed_runs
    misses = missed_runs(root)
    join_misses = []
    if pulse_exists:
        try:
            from .pulse import load_activity_pulse
            join_misses = load_activity_pulse(root).get("diagnostics", {}).get("queue_join_misses", [])
        except Exception:
            join_misses = []
    warnings = status_warnings(load_last_run(root), misses, join_misses)

    accounts_health = []
    for acct in list_accounts():
        acct_id = str(acct.get("account_id") or "default")
        acct_root = _account_root(acct_id)
        freshness = account_freshness(acct_root)
        accounts_health.append(
            {
                "account_id": acct_id,
                "type": acct.get("type"),
                "email": acct.get("email"),
                "password_set": bool(acct.get("password_set")),
                "is_default": bool(acct.get("is_default")),
                "freshness": freshness,
            }
        )
    if not accounts_health:
        accounts_health.append(
            {
                "account_id": aid,
                "type": "personal",
                "email": imap_cfg.get("login") or "",
                "password_set": bool(imap_cfg.get("password")),
                "freshness": account_freshness(root),
            }
        )

    return {
        "ok": True,
        "state_root": str(root),
        "account_id": aid,
        "source_account": aid,
        "imap": {
            "host": imap_cfg.get("host", ""),
            "login": imap_cfg.get("login", ""),
            "preflight": pf,
        },
        "llm": {"ok": llm_ok, "error": llm_err if not llm_ok else None},
        "artifacts": {
            "phase1_context": context_exists,
            "activity_pulse": pulse_exists,
        },
        "pipeline": {
            "fetch": _mtime_iso(context_path),
            "analysis": _mtime_iso(analysis_path),
            "pulse": _mtime_iso(pulse_path),
        },
        "freshness": account_freshness(root),
        "recent_runs": load_recent_runs(root, limit=10),
        "accounts": accounts_health,
        "missed_runs": misses,
        "diagnostics": {"queue_join_misses": join_misses},
        "warnings": warnings,
    }



def cmd_accounts(remaining: list[str], account_id: str | None = None) -> dict[str, Any]:
    from .config import (
        default_account_id,
        get_account,
        list_accounts,
        remove_account,
        set_default_account,
        upsert_account,
    )

    if not remaining or remaining[0] in {"list", "ls"}:
        rows = list_accounts()
        return {
            "ok": True,
            "accounts": rows,
            "count": len(rows),
            "default_account_id": default_account_id(),
        }

    action = remaining[0]
    if action == "get":
        aid = remaining[1] if len(remaining) > 1 else (account_id or "")
        row = get_account(aid or None)
        if not row:
            return {"ok": False, "error": "account not found"}
        return {"ok": True, "account": row}

    if action == "remove":
        aid = remaining[1] if len(remaining) > 1 else (account_id or "")
        if not aid:
            return {"ok": False, "error": "Usage: accounts remove <account_id>"}
        return remove_account(aid)

    if action in {"set-default", "setdefault"}:
        aid = remaining[1] if len(remaining) > 1 else (account_id or "")
        if not aid:
            return {"ok": False, "error": "Usage: accounts set-default <account_id>"}
        try:
            return set_default_account(aid)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    if action == "add":
        kwargs: dict[str, Any] = {}
        i = 1
        while i < len(remaining):
            a = remaining[i]
            if a.startswith("--") and i + 1 < len(remaining):
                key = a[2:].replace("-", "_")
                kwargs[key] = remaining[i + 1]
                i += 2
            else:
                i += 1
        aid = str(kwargs.get("account_id") or kwargs.get("id") or account_id or "").strip()
        if not aid:
            return {"ok": False, "error": "accounts add requires --account-id"}
        account_id = aid
        try:
            return upsert_account(
                account_id=account_id,
                email=str(kwargs.get("email") or ""),
                account_type=str(kwargs.get("type") or "personal"),
                host=str(kwargs.get("host") or ""),
                port=int(kwargs.get("port") or 993),
                login=str(kwargs.get("login") or kwargs.get("email") or ""),
                password=str(kwargs.get("password") or ""),
                encryption=str(kwargs.get("encryption") or "tls"),
                make_default=str(kwargs.get("default") or "").lower() in {"1", "true", "yes"},
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    return {"ok": False, "error": "Usage: accounts [list|get|add|remove|set-default] ..."}


def cmd_ingest(remaining: list[str], account_id: str | None = None) -> dict[str, Any]:
    from .adapter import build_ingest_envelopes
    from .config import default_account_id

    aid = account_id or default_account_id()
    since = ""
    limit = 50
    i = 0
    while i < len(remaining):
        a = remaining[i]
        if a == "--since" and i + 1 < len(remaining):
            since = remaining[i + 1]
            i += 2
        elif a == "--limit" and i + 1 < len(remaining):
            limit = int(remaining[i + 1])
            i += 2
        else:
            i += 1
    return build_ingest_envelopes(_account_root(aid), account_id=aid, since_cursor=since, limit=limit)


def cmd_realtime_watch(remaining: list[str], account_id: str | None = None) -> dict[str, Any]:
    """Run the supervised realtime ingress worker; this never starts a daemon."""
    from .config import resolve_imap_config
    from .realtime_mail_events import RealtimeMailWorker

    aid = _resolved_account_id(account_id)
    imap_cfg = resolve_imap_config(aid)
    if not imap_cfg.get("host") or not imap_cfg.get("login") or not imap_cfg.get("password"):
        return {"ok": False, "error": "imap_not_configured", "recovery_tool": "twinbox_setup"}

    def _seconds(flag: str, default: float, *, minimum: float = 0.0) -> float:
        if flag not in remaining:
            return default
        index = remaining.index(flag)
        if index + 1 >= len(remaining):
            raise ValueError(f"{flag}_value_required")
        value = float(remaining[index + 1])
        if value < minimum:
            raise ValueError(f"{flag}_must_be_at_least_{minimum:g}")
        return value

    once = "--once" in remaining
    max_cycles: int | None = 1 if once else None
    if "--max-cycles" in remaining:
        index = remaining.index("--max-cycles")
        if index + 1 >= len(remaining):
            return {"ok": False, "error": "max_cycles_value_required"}
        max_cycles = int(remaining[index + 1])
        if max_cycles < 1:
            return {"ok": False, "error": "max_cycles_must_be_positive"}
    try:
        worker = RealtimeMailWorker(
            state_root=_account_root(aid),
            account_id=aid,
            imap_config=imap_cfg,
            idle_timeout_seconds=_seconds("--idle-timeout-seconds", 29 * 60, minimum=1),
            poll_interval_seconds=_seconds("--poll-interval-seconds", 5 * 60, minimum=1),
            reconnect_backoff_seconds=_seconds("--reconnect-backoff-seconds", 5, minimum=0),
        )
        return worker.run(max_cycles=max_cycles)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}



def cmd_events(remaining: list[str], account_id: str | None = None) -> dict[str, Any]:
    from .adapter import load_event_records
    from .config import default_account_id

    aid = account_id or default_account_id()
    limit = 50
    i = 0
    while i < len(remaining):
        a = remaining[i]
        if a == "--limit" and i + 1 < len(remaining):
            limit = int(remaining[i + 1])
            i += 2
        else:
            i += 1
    return load_event_records(_account_root(aid), account_id=aid, limit=limit)


def cmd_case_ledger(remaining: list[str], account_id: str | None = None) -> dict[str, Any]:
    from . import case_ledger

    root = _account_root(account_id)
    view = case_ledger.current_view(root)
    cases = [
        {
            "case_ref": ref,
            "attribute": attribute,
            "value": record.get("value"),
            "valid_from": record.get("valid_from"),
            "recorded_at": record.get("recorded_at"),
            "evidence_ref": record.get("evidence_ref"),
            "source": record.get("source"),
            "status": record.get("status"),
        }
        for (ref, attribute), record in sorted(view.items())
    ]
    return {"ok": True, "cases": cases}


def cmd_taxonomy(remaining: list[str], account_id: str | None = None) -> dict[str, Any]:
    from . import taxonomy

    root = _account_root(account_id)
    sub = remaining[0] if remaining else ""
    if sub == "induce":
        lookback, rest = _parse_flag(remaining[1:], "--lookback")
        budget, _rest = _parse_flag(rest, "--budget")
        return taxonomy.induce(
            root,
            lookback_days=int(lookback) if lookback and lookback.isdigit() else None,
            budget=int(budget) if budget and budget.isdigit() else 3,
        )
    if sub == "confirm":
        return taxonomy.confirm(root)
    if sub == "drift":
        return taxonomy.record_drift(root)
    return {"ok": False, "error": "Usage: taxonomy induce|confirm|drift"}


def cmd_semantics(remaining: list[str], account_id: str | None = None) -> dict[str, Any]:
    from .classification_store import classification_path
    from .semantic_client import project_semantics

    aid = _resolved_account_id(account_id)
    root = _account_root(aid)
    action = remaining[0] if remaining and not remaining[0].startswith("--") else "list"
    case = ""
    include_evidence = "--include-evidence" in remaining
    for i, arg in enumerate(remaining):
        if arg == "--case-ref" and i + 1 < len(remaining):
            case = remaining[i + 1]
    # Scope comes from the local classification authority, never from tool input.
    scope_id = aid
    path = classification_path(root)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw.get("scope_id"):
                scope_id = str(raw["scope_id"])
        except (OSError, json.JSONDecodeError):
            pass
    data = project_semantics(root, scope_id=scope_id, action=action, case_ref=case,
                             include_evidence=include_evidence)
    return {"ok": "error" not in data, "data": data,
            **({"error": data["error"]} if "error" in data else {})}


def _trusted_feedback_context(root: Path, aid: str, payload: dict[str, Any]):
    from .evidence_contract import SourceGrant

    path = root / "config" / "source-grant.json"
    if not path.is_file():
        raise ValueError("source_grant_missing")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("source_grant_invalid") from None
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        raise ValueError("source_grant_invalid")
    if str(raw.get("account_ref") or "") != aid:
        raise ValueError("source_binding_invalid")
    actors = raw.get("actors")
    actor = str(payload.get("actor_ref") or "")
    kinds = actors.get(actor) if isinstance(actors, dict) else None
    if not isinstance(kinds, list):
        raise ValueError("actor_forbidden")
    grant = SourceGrant(
        scope_id=str(raw.get("scope_id") or ""), account_ref=aid,
        mail_refs=frozenset(str(v) for v in raw.get("mail_refs", []) if isinstance(v, str)),
        evidence_refs=frozenset(str(v) for v in raw.get("evidence_refs", []) if isinstance(v, str)),
        enabled=raw.get("enabled") is True,
    )
    return grant, actor, frozenset(str(v) for v in kinds)


def cmd_feedback(remaining: list[str], account_id: str | None = None) -> dict[str, Any]:
    from .feedback import FeedbackStoreError, process_feedback

    aid = _resolved_account_id(account_id)
    root = _account_root(aid)
    payload_json = ""
    payload_file = ""
    for i, arg in enumerate(remaining):
        if arg == "--payload-json" and i + 1 < len(remaining):
            payload_json = remaining[i + 1]
        elif arg == "--payload-file" and i + 1 < len(remaining):
            payload_file = remaining[i + 1]
    try:
        if payload_file:
            payload = json.loads(Path(payload_file).read_text(encoding="utf-8"))
        elif payload_json:
            payload = json.loads(payload_json)
        else:
            return {"ok": False, "error": "feedback_payload_required", "recovery_tool": "twinbox_semantics"}
        if not isinstance(payload, dict):
            raise ValueError("invalid_payload")
        grant, actor, kinds = _trusted_feedback_context(root, aid, payload)
        result = process_feedback(root, payload, grant=grant, actor_ref=actor, allowed_kinds=kinds)
        return {"ok": True, "data": result}
    except (FeedbackStoreError, ValueError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc), "recovery_tool": "twinbox_semantics"}


def _trusted_weknora_grant(root: Path, aid: str):
    """Load a local source grant; CLI payloads cannot confer retrieval authority."""
    from .evidence_contract import SourceGrant

    path = root / "config" / "source-grant.json"
    if not path.is_file():
        raise ValueError("source_grant_missing")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("source_grant_invalid") from None
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        raise ValueError("source_grant_invalid")
    if str(raw.get("account_ref") or "") != aid:
        raise ValueError("source_binding_invalid")
    return SourceGrant(
        scope_id=str(raw.get("scope_id") or ""),
        account_ref=aid,
        mail_refs=frozenset(str(v) for v in raw.get("mail_refs", []) if isinstance(v, str)),
        evidence_refs=frozenset(str(v) for v in raw.get("evidence_refs", []) if isinstance(v, str)),
        enabled=raw.get("enabled") is True,
    )


def _live_provider_or_unavailable(
    root: Path,
    aid: str,
    settings: dict[str, bool],
    *,
    require_grant_enabled: bool = True,
):
    """Build the live HTTP provider only behind the triple gate, else None."""
    from .weknora import WeKnoraSyncError
    from .weknora_http import build_http_provider, live_authorized

    try:
        grant = _trusted_weknora_grant(root, aid)
    except ValueError:
        return None
    if not live_authorized(
        settings=settings, grant=grant, require_grant_enabled=require_grant_enabled,
    ):
        return None
    try:
        return build_http_provider()
    except WeKnoraSyncError:
        return None


class _PendingDeleteProvider:
    """No-network stub so revoke can hide locally when the live gate is closed."""

    def delete_excerpt(self, scope: str, knowledge_ref: str) -> dict[str, str]:
        return {"status": "pending"}


def cmd_weknora(
    remaining: list[str],
    account_id: str | None = None,
    *,
    provider: object | None = None,
) -> dict[str, Any]:
    """Expose local diagnostics, gated sync, and hide-then-delete revoke.

    ``provider`` dependency injection stays for local fake-provider tests.  When
    it is omitted, the CLI builds a live HTTP provider only if the triple gate
    holds (enabled flag + ADR-004 acceptance + per-scope source grant) and
    credentials plus the dedicated KB binding resolve; otherwise sync stays
    unavailable with no network attempt.  Revoke still hides locally when the
    live gate is closed, and may delete remotely after the grant is turned off.
    """
    from .weknora import WeKnoraSyncError, revoke_excerpt, sync_diagnostics, sync_excerpt

    aid = _resolved_account_id(account_id)
    root = _account_root(aid)
    action = remaining[0] if remaining and not remaining[0].startswith("--") else "status"
    args = remaining[1:] if remaining and not remaining[0].startswith("--") else remaining
    settings = get_weknora_config()
    if action == "status":
        diagnostics = sync_diagnostics(root)
        return {
            "ok": True,
            "data": {
                "enabled": settings["enabled"],
                "adr_004_accepted": settings.get("adr_004_accepted", False),
                "provider_port_verified": settings["provider_port_verified"],
                "live_provider_available": False,
                "diagnostics": diagnostics,
            },
        }
    if action == "revoke":
        mail_ref, _rest = _parse_flag(args, "--mail-ref")
        if not mail_ref:
            return {"ok": False, "error": "weknora_usage", "recovery_tool": "twinbox_status"}
        if provider is None:
            provider = _live_provider_or_unavailable(
                root, aid, settings, require_grant_enabled=False,
            )
            if provider is None:
                provider = _PendingDeleteProvider()
        try:
            grant = _trusted_weknora_grant(root, aid)
            result = revoke_excerpt(root, provider, grant, mail_ref=mail_ref)
            return {"ok": True, "data": result}
        except (WeKnoraSyncError, ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc), "recovery_tool": "twinbox_status"}
    if action != "sync":
        return {"ok": False, "error": "weknora_usage", "recovery_tool": "twinbox_status"}
    if not settings["enabled"]:
        return {"ok": False, "error": "weknora_disabled", "recovery_tool": "twinbox_status"}
    if provider is None:
        provider = _live_provider_or_unavailable(root, aid, settings)
        if provider is None:
            return {"ok": False, "error": "weknora_provider_unavailable", "recovery_tool": "twinbox_status"}

    payload_json = ""
    payload_file = ""
    for i, arg in enumerate(args):
        if arg == "--payload-json" and i + 1 < len(args):
            payload_json = args[i + 1]
        elif arg == "--payload-file" and i + 1 < len(args):
            payload_file = args[i + 1]
    try:
        if payload_file:
            payload = json.loads(Path(payload_file).read_text(encoding="utf-8"))
        elif payload_json:
            payload = json.loads(payload_json)
        else:
            return {"ok": False, "error": "weknora_payload_required", "recovery_tool": "twinbox_status"}
        if not isinstance(payload, dict):
            raise ValueError("invalid_payload")
        grant = _trusted_weknora_grant(root, aid)
        result = sync_excerpt(root, provider, grant, payload)
        return {"ok": True, "data": result}
    except (WeKnoraSyncError, ValueError, OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": str(exc), "recovery_tool": "twinbox_status"}


# --- Main ---

# --- Main ---

def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__, file=sys.stderr)
        return 1

    cmd = args[0]
    json_mode = "--json" in args
    remaining = [a for a in args[1:] if a != "--json"]
    account_id, remaining = _parse_flag(remaining, "--account-id")

    try:
        if cmd == "setup":
            result = cmd_setup()
        elif cmd == "sync":
            job = "daytime-sync"
            for i, a in enumerate(remaining):
                if a == "--job" and i + 1 < len(remaining):
                    job = remaining[i + 1]
            result = cmd_sync(job, account_id=account_id)
        elif cmd == "latest-mail":
            unread = "--unread-only" in remaining
            result = cmd_latest_mail(unread, account_id=account_id)
        elif cmd == "todo":
            result = cmd_todo(account_id=account_id)
        elif cmd == "weekly":
            result = cmd_weekly(account_id=account_id)
        elif cmd == "thread":
            query = remaining[0] if remaining else ""
            result = cmd_thread_inspect(query, account_id=account_id)
        elif cmd == "extract":
            result = cmd_extract(remaining, account_id=account_id)
        elif cmd == "queue":
            action = remaining[0] if remaining else ""
            thread_key = remaining[1] if len(remaining) > 1 else ""
            reason = ""
            for i, a in enumerate(remaining):
                if a in ("--reason", "--action-taken") and i + 1 < len(remaining):
                    reason = remaining[i + 1]
            if not action or not thread_key:
                result = {"ok": False, "error": "Usage: queue <complete|dismiss|restore> <thread_key>"}
            else:
                result = cmd_queue_action(action, thread_key, reason, account_id=account_id)
        elif cmd == "status":
            result = cmd_status(account_id=account_id)
        elif cmd == "accounts":
            result = cmd_accounts(remaining, account_id=account_id)
        elif cmd == "ingest":
            result = cmd_ingest(remaining, account_id=account_id)
        elif cmd == "events":
            result = cmd_events(remaining, account_id=account_id)
        elif cmd == "case-ledger":
            result = cmd_case_ledger(remaining, account_id=account_id)
        elif cmd == "taxonomy":
            result = cmd_taxonomy(remaining, account_id=account_id)
        elif cmd == "realtime-watch":
            result = cmd_realtime_watch(remaining, account_id=account_id)
        elif cmd == "semantics":
            result = cmd_semantics(remaining, account_id=account_id)
        elif cmd == "feedback":
            result = cmd_feedback(remaining, account_id=account_id)
        elif cmd == "weknora":
            result = cmd_weknora(remaining, account_id=account_id)
        elif cmd == "schedule":
            sub = remaining[0] if remaining else ""
            if sub == "run-due":
                from .schedule import run_due
                result = run_due(_account_root(account_id), code_root=_code_root())
            else:
                result = {"ok": False, "error": "Usage: schedule run-due"}
        elif cmd == "onboard":
            answers = {}
            for i, a in enumerate(remaining):
                if a.startswith("--") and i + 1 < len(remaining):
                    answers[a[2:].replace("-", "_")] = remaining[i + 1]
            from .onboard import save_user_pack
            from . import taxonomy
            result = save_user_pack(_account_root(account_id), answers)
            if result.get("ok"):
                try:
                    draft = taxonomy.induce(_account_root(account_id))
                    result["taxonomy_draft"] = {
                        "ok": draft.get("ok"),
                        "path": draft.get("path"),
                        "stop": draft.get("stop"),
                        "categories": draft.get("categories"),
                    }
                except Exception as exc:  # fail-open: onboard already succeeded
                    result["taxonomy_draft"] = {"ok": False, "error": type(exc).__name__}
        elif cmd == "material-import":
            path = remaining[0] if remaining else ""
            intent = "reference"
            for i, a in enumerate(remaining):
                if a == "--intent" and i + 1 < len(remaining):
                    intent = remaining[i + 1]
            if not path:
                result = {"ok": False, "error": "Usage: material-import PATH"}
            else:
                from .material_import import import_material
                result = import_material(Path(path), intent=intent)
        elif cmd == "actions":
            sub = remaining[0] if remaining else "list"
            from .actions import scan_proposals, review_proposal
            if sub == "review":
                confirmation_token, review_args = _parse_flag(remaining, "--confirmation-token")
                reason, review_args = _parse_flag(review_args, "--reason")
                pid = review_args[1] if len(review_args) > 1 else ""
                action = review_args[2] if len(review_args) > 2 else "confirm"
                result = review_proposal(
                    _account_root(account_id),
                    pid,
                    action,
                    reason=reason or "",
                    confirmation_token=confirmation_token,
                )
            else:
                result = scan_proposals(_account_root(account_id))
        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            print(__doc__, file=sys.stderr)
            return 1

        _json_out(result)
        return 0 if result.get("ok", True) else 1

    except Exception as exc:
        _json_out({"ok": False, "error": str(exc)})
        return 1



if __name__ == "__main__":
    raise SystemExit(main())
