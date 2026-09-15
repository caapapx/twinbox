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
  onboard      — write user semantic pack from questionnaire answers
  material-import — optional xlsx/docx pack fragment
  actions      — dry-run proposals / review
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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


def _json_out(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


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

    fetch_started = time.monotonic()
    fetch_result = fetch_incremental(
        root, folders, imap_cfg,
        sample_body_count=30, lookback_days=lookback,
        account_id=aid,
    )
    if fetch_result.get("status") == "error":
        msg = str(fetch_result.get("error") or "fetch failed")
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

    degraded: list[str] = []
    analysis_started = time.monotonic()
    if quick:
        analysis: dict[str, Any] = {"ok": True, "skipped": True, "reason": "quick-refresh"}
    else:
        analysis = run_analysis(root)
        if not analysis.get("ok"):
            degraded.append("analysis")
    analysis_ms = round((time.monotonic() - analysis_started) * 1000)

    pulse_started = time.monotonic()
    try:
        pulse_data, pulse_path = write_activity_pulse(root)
        pulse_ok = True
        from .pulse import _load_yaml
        urgent_yaml = root / "runtime" / "validation" / "phase-4" / "daily-urgent.yaml"
        pulse_data["analysis_generated_at"] = _load_yaml(urgent_yaml).get("generated_at") or None
        if quick:
            pulse_data["analysis_skipped"] = True
        if "analysis" in degraded:
            pulse_data["stale_analysis"] = True
        pulse_data["source_account"] = aid
        from .imap_fetch import _write_json
        _write_json(pulse_path, pulse_data)
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
                "analysis": "skipped" if quick else ("degraded" if "analysis" in degraded else "ok"),
                "pulse": "ok" if pulse_ok else "error",
            },
        },
    )

    return {
        "ok": True if pulse_ok else False,
        "job": job,
        "account_id": aid,
        "run_id": run_id,
        "source_account": aid,
        "degraded": degraded,
        "fetch": fetch_result,
        "analysis": analysis,
        "pulse": {"ok": pulse_ok, "tracked_threads": pulse_data.get("summary", {}).get("tracked_threads", 0)},
        "consistency": {
            "fetch_at": fetch_at,
            "analysis_ok": analysis.get("ok"),
            "analysis_skipped": quick,
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


def cmd_latest_mail(unread_only: bool = False, account_id: str | None = None) -> dict[str, Any]:
    from .pulse import load_activity_pulse
    root = _account_root(account_id)
    try:
        pulse = load_activity_pulse(root)
    except RuntimeError:
        return _recovery_hint("twinbox_sync", "Missing activity-pulse.json")

    threads = pulse.get("thread_index", [])
    if unread_only:
        threads = [t for t in threads if isinstance(t, dict) and t.get("unread_count", 0) > 0]

    return {
        "ok": True,
        "source_account": (account_id or "default"),
        "generated_at": pulse.get("generated_at", ""),
        "staleness": _staleness(str(pulse.get("generated_at", "") or "")),
        "summary": pulse.get("summary", {}),
        "threads": threads[:30],
        "recent_activity": pulse.get("recent_activity", []),
        "needs_attention": pulse.get("needs_attention", []),
        "projections": pulse.get("projections", {}),
    }


def cmd_todo(account_id: str | None = None) -> dict[str, Any]:
    from .pulse import load_activity_pulse
    root = _account_root(account_id)
    try:
        pulse = load_activity_pulse(root)
    except RuntimeError:
        return _recovery_hint("twinbox_sync", "Missing activity-pulse.json")

    attention = pulse.get("needs_attention", [])
    return {
        "ok": True,
        "generated_at": pulse.get("generated_at", ""),
        "staleness": _staleness(str(pulse.get("generated_at", "") or "")),
        "needs_attention": attention,
        "projections": pulse.get("projections", {}),
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
    }


def cmd_thread_inspect(query: str, account_id: str | None = None) -> dict[str, Any]:
    from .pulse import search_threads
    root = _account_root(account_id)
    try:
        results = search_threads(query, root, limit=10)
    except RuntimeError:
        return _recovery_hint("twinbox_sync", "Missing activity-pulse.json")
    return {"ok": True, "query": query, "results": results, "count": len(results)}


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

    return run_extract(_account_root(account_id), criteria, code_root=_code_root())


def cmd_queue_action(action: str, thread_key: str, reason: str = "", account_id: str | None = None) -> dict[str, Any]:
    from .queue import complete_thread, dismiss_thread, restore_thread
    root = _account_root(account_id)
    if action == "complete":
        return complete_thread(root, thread_key, reason or "已完成")
    elif action == "dismiss":
        return dismiss_thread(root, thread_key, reason or "已处理")
    elif action == "restore":
        return restore_thread(root, thread_key)
    return {"ok": False, "error": f"Unknown action: {action}"}



def cmd_status(account_id: str | None = None) -> dict[str, Any]:
    from .config import resolve_imap_config, list_accounts, default_account_id
    from .imap_fetch import preflight
    from .llm import validate_backend
    from .runs import account_freshness, load_recent_runs

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
    warnings = []
    if misses:
        warnings.append({"missed_runs": misses})
    if join_misses:
        warnings.append({"queue_join_misses": join_misses})

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
    from .config import list_accounts, upsert_account, remove_account, get_account

    if not remaining or remaining[0] in {"list", "ls"}:
        rows = list_accounts()
        return {"ok": True, "accounts": rows, "count": len(rows)}

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

    return {"ok": False, "error": "Usage: accounts [list|get|add|remove] ..."}


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
            result = save_user_pack(_account_root(account_id), answers)
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
                pid = remaining[1] if len(remaining) > 1 else ""
                action = remaining[2] if len(remaining) > 2 else "confirm"
                result = review_proposal(_account_root(account_id), pid, action)
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
