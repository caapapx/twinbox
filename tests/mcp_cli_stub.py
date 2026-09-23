#!/usr/bin/env python3
"""Stand-in python for MCP autosync tests. Logs CLI argv; no IMAP."""
from __future__ import annotations

import json
import os
import sys


def _log(cli_args: list[str]) -> None:
    path = os.environ.get("TWINBOX_CLI_ARGV_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(cli_args, ensure_ascii=False) + "\n")


def _emit(payload: dict, code: int = 0) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return code


def main(argv: list[str]) -> int:
    # spawn(python, ["-m", "twinbox_core.cli", ...])
    args = argv[1:]
    if args[:2] == ["-m", "twinbox_core.cli"]:
        args = args[2:]
    _log(args)
    if not args:
        return _emit({"ok": False, "error": "empty argv"}, 1)

    cmd = args[0]
    if cmd == "sync":
        mode = os.environ.get("TWINBOX_STUB_SYNC", "fail")
        if mode == "ok":
            return _emit({"ok": True, "job": "stub", "degraded": []})
        if mode == "degraded":
            return _emit({"ok": True, "job": "stub", "degraded": ["analysis"]})
        return _emit({"ok": False, "error": "stub sync fail"}, 1)

    query_mode = os.environ.get("TWINBOX_STUB_QUERY", "missing")
    if query_mode == "ok":
        return _emit({"ok": True, "generated_at": "2026-09-18T00:00:00+08:00"})
    if query_mode == "stale":
        return _emit(
            {
                "ok": True,
                "generated_at": "2000-01-01T00:00:00+08:00",
                "stale": True,
            }
        )

    if cmd == "weekly":
        return _emit(
            {
                "ok": False,
                "recovery_tool": "twinbox_sync",
                "error": "Missing weekly-brief-raw.json. Run sync with job=nightly-full.",
            }
        )
    return _emit(
        {
            "ok": False,
            "recovery_tool": "twinbox_sync",
            "error": "Missing activity-pulse.json",
        }
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
