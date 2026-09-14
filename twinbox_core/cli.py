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


def cmd_sync(job: str = "daytime-sync") -> dict[str, Any]:
    from .config import resolve_imap_config
    from .imap_fetch import fetch_incremental
    from .analyze import run_analysis
    from .pulse import write_activity_pulse

    root = _state_root()
    imap_cfg = resolve_imap_config()
    if not imap_cfg.get("host") or not imap_cfg.get("login"):
        return {"ok": False, "error": "IMAP not configured. Run setup first."}

    folders = ["INBOX"]
    lookback = 30 if job == "nightly-full" else 7
    # quick-refresh: fetch + embed + rebuild pulse, keep the last scheduled LLM analysis.
    # Kept for explicit lightweight refreshes; scheduled full analysis stays with cron
    # or an explicit daytime-sync request.
    quick = job == "quick-refresh"

    # Step 1: Fetch envelopes + bodies
    fetch_started = time.monotonic()
    fetch_result = fetch_incremental(
        root, folders, imap_cfg,
        sample_body_count=30, lookback_days=lookback,
    )
    if fetch_result.get("status") == "error":
        return {"ok": False, "step": "fetch", **fetch_result}
    fetch_ms = round((time.monotonic() - fetch_started) * 1000)

    # Step 2: LLM analysis (urgent / pending / sla / weekly)
    degraded: list[str] = []
    analysis_started = time.monotonic()
    if quick:
        analysis: dict[str, Any] = {"ok": True, "skipped": True, "reason": "quick-refresh"}
    else:
        analysis = run_analysis(root)
        if not analysis.get("ok"):
            degraded.append("analysis")
    analysis_ms = round((time.monotonic() - analysis_started) * 1000)

    # Step 3: Build activity pulse
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
        from .imap_fetch import _write_json
        _write_json(pulse_path, pulse_data)
    except Exception as exc:
        pulse_ok = False
        pulse_data = {"error": str(exc)}

    pulse_ms = round((time.monotonic() - pulse_started) * 1000)
    fetch_at = fetch_result.get("generated_at") or ""
    return {
        "ok": True,
        "job": job,
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
        "timings_ms": {
            "fetch_ms": fetch_ms,
            "analysis_ms": analysis_ms,
            "pulse_ms": pulse_ms,
            **(fetch_result.get("timings_ms") if isinstance(fetch_result.get("timings_ms"), dict) else {}),
        },
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


def cmd_latest_mail(unread_only: bool = False) -> dict[str, Any]:
    from .pulse import load_activity_pulse
    root = _state_root()
    try:
        pulse = load_activity_pulse(root)
    except RuntimeError:
        return _recovery_hint("twinbox_sync", "Missing activity-pulse.json")

    threads = pulse.get("thread_index", [])
    if unread_only:
        threads = [t for t in threads if isinstance(t, dict) and t.get("unread_count", 0) > 0]

    return {
        "ok": True,
        "generated_at": pulse.get("generated_at", ""),
        "staleness": _staleness(str(pulse.get("generated_at", "") or "")),
        "summary": pulse.get("summary", {}),
        "threads": threads[:30],
        "recent_activity": pulse.get("recent_activity", []),
        "needs_attention": pulse.get("needs_attention", []),
        "projections": pulse.get("projections", {}),
    }


def cmd_todo() -> dict[str, Any]:
    from .pulse import load_activity_pulse
    root = _state_root()
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


def cmd_weekly() -> dict[str, Any]:
    root = _state_root()
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


def cmd_thread_inspect(query: str) -> dict[str, Any]:
    from .pulse import search_threads
    root = _state_root()
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


def cmd_extract(remaining: list[str]) -> dict[str, Any]:
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

    return run_extract(_state_root(), criteria, code_root=_code_root())


def cmd_queue_action(action: str, thread_key: str, reason: str = "") -> dict[str, Any]:
    from .queue import complete_thread, dismiss_thread, restore_thread
    root = _state_root()
    if action == "complete":
        return complete_thread(root, thread_key, reason or "已完成")
    elif action == "dismiss":
        return dismiss_thread(root, thread_key, reason or "已处理")
    elif action == "restore":
        return restore_thread(root, thread_key)
    return {"ok": False, "error": f"Unknown action: {action}"}


def cmd_status() -> dict[str, Any]:
    from .config import resolve_imap_config, load_config, mask_secret
    from .imap_fetch import preflight
    from .llm import validate_backend

    root = _state_root()
    imap_cfg = resolve_imap_config()
    pf = preflight(imap_cfg)

    llm_ok, llm_err = validate_backend()

    # Check for artifacts
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

    return {
        "ok": True,
        "state_root": str(root),
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
        "missed_runs": misses,
        "diagnostics": {"queue_join_misses": join_misses},
        "warnings": warnings,
    }


# --- Main ---

def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(__doc__, file=sys.stderr)
        return 1

    cmd = args[0]
    json_mode = "--json" in args
    remaining = [a for a in args[1:] if a != "--json"]

    try:
        if cmd == "setup":
            result = cmd_setup()
        elif cmd == "sync":
            job = "daytime-sync"
            for i, a in enumerate(remaining):
                if a == "--job" and i + 1 < len(remaining):
                    job = remaining[i + 1]
            result = cmd_sync(job)
        elif cmd == "latest-mail":
            unread = "--unread-only" in remaining
            result = cmd_latest_mail(unread)
        elif cmd == "todo":
            result = cmd_todo()
        elif cmd == "weekly":
            result = cmd_weekly()
        elif cmd == "thread":
            query = remaining[0] if remaining else ""
            result = cmd_thread_inspect(query)
        elif cmd == "extract":
            result = cmd_extract(remaining)
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
                result = cmd_queue_action(action, thread_key, reason)
        elif cmd == "status":
            result = cmd_status()
        elif cmd == "schedule":
            sub = remaining[0] if remaining else ""
            if sub == "run-due":
                from .schedule import run_due
                result = run_due(_state_root(), code_root=_code_root())
            else:
                result = {"ok": False, "error": "Usage: schedule run-due"}
        elif cmd == "onboard":
            answers = {}
            for i, a in enumerate(remaining):
                if a.startswith("--") and i + 1 < len(remaining):
                    answers[a[2:].replace("-", "_")] = remaining[i + 1]
            from .onboard import save_user_pack
            result = save_user_pack(_state_root(), answers)
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
                result = review_proposal(_state_root(), pid, action)
            else:
                result = scan_proposals(_state_root())
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
