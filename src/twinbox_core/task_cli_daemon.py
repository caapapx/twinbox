"""`twinbox daemon` subcommands — thin wrapper over twinbox_core.daemon.lifecycle."""

from __future__ import annotations

import argparse

from twinbox_core.daemon.lifecycle import main_daemon_subcommand


def register_daemon_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    d = subparsers.add_parser("daemon", help="Background JSON-RPC daemon (Unix socket)")
    d_sub = d.add_subparsers(dest="daemon_command", required=True)
    d_sub.add_parser("start", help="Start daemon process")
    d_sub.add_parser("stop", help="Stop daemon (SIGTERM, then SIGKILL)")
    d_sub.add_parser("restart", help="Stop then start daemon")
    st = d_sub.add_parser("status", help="Show daemon status (or JSON with --json)")
    st.add_argument("--json", action="store_true", help="Emit machine-readable status JSON")


def dispatch_daemon(args: argparse.Namespace) -> int:
    sub = args.daemon_command
    json_out = getattr(args, "json", False) if sub == "status" else False
    return main_daemon_subcommand(sub, json_output=json_out)
