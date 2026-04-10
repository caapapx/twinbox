"""Twinbox Lite CLI — lightweight entry point for OpenClaw skill.

Usage: python3 -m twinbox_core.cli <command> [--json]

Commands:
  setup        — Validate IMAP + import LLM from OpenClaw
  sync         — Fetch mail + run LLM analysis
  latest-mail  — Latest mail / activity pulse snapshot
  todo         — Urgent / pending queue
  weekly       — Weekly brief
  thread       — Inspect or search threads
  queue        — Mark thread complete / dismiss / restore
  status       — Mailbox health + setup status
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


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
    lookback = 7 if job == "daytime-sync" else 30

    # Step 1: Fetch envelopes + bodies
    fetch_result = fetch_incremental(
        root, folders, imap_cfg,
        sample_body_count=30, lookback_days=lookback,
    )
    if fetch_result.get("status") == "error":
        return {"ok": False, "step": "fetch", **fetch_result}

    # Step 2: LLM analysis (urgent / pending / sla / weekly)
    analysis = run_analysis(root)

    # Step 3: Build activity pulse
    try:
        pulse_data, pulse_path = write_activity_pulse(root)
        pulse_ok = True
    except Exception as exc:
        pulse_ok = False
        pulse_data = {"error": str(exc)}

    return {
        "ok": True,
        "job": job,
        "fetch": fetch_result,
        "analysis": analysis,
        "pulse": {"ok": pulse_ok, "tracked_threads": pulse_data.get("summary", {}).get("tracked_threads", 0)},
    }


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
        "summary": pulse.get("summary", {}),
        "threads": threads[:30],
        "recent_activity": pulse.get("recent_activity", []),
        "needs_attention": pulse.get("needs_attention", []),
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
        "needs_attention": attention,
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
    return {"ok": True, **data}


def cmd_thread_inspect(query: str) -> dict[str, Any]:
    from .pulse import search_threads
    root = _state_root()
    try:
        results = search_threads(query, root, limit=10)
    except RuntimeError:
        return _recovery_hint("twinbox_sync", "Missing activity-pulse.json")
    return {"ok": True, "query": query, "results": results, "count": len(results)}


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
    pulse_exists = (root / "runtime" / "validation" / "phase-4" / "activity-pulse.json").is_file()
    context_exists = (root / "runtime" / "context" / "phase1-context.json").is_file()

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
