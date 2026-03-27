"""`twinbox loading` — Python entrypoints for phase loading."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from twinbox_core.paths import PathResolutionError, resolve_state_root


def register_loading_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    load = subparsers.add_parser(
        "loading",
        help="Phase mailbox loading",
    )
    sub = load.add_subparsers(dest="loading_command", required=True)
    for n in (1, 2, 3, 4):
        p = sub.add_parser(f"phase{n}", help=f"Run phase{n}_loading.sh")
        p.add_argument(
            "script_args",
            nargs=argparse.REMAINDER,
            help="Extra args forwarded to the bash script",
        )


def dispatch_loading(args: argparse.Namespace) -> int:
    cmd = args.loading_command
    if not cmd.startswith("phase") or not cmd[5:].isdigit():
        print(f"未知 loading 子命令: {cmd}", file=sys.stderr)
        return 2
    n = int(cmd[5:])
    cwd = Path.cwd()
    try:
        state_root = resolve_state_root(cwd)
    except PathResolutionError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    extra = list(getattr(args, "script_args", []) or [])
    if extra and extra[0] == "--":
        extra = extra[1:]
    if n in (1, 4):
        from twinbox_core import loading_pipeline

        return loading_pipeline.main([cmd, "--state-root", str(state_root), *extra])
    if n == 2:
        from twinbox_core.context_builder import run_phase2_loading

        run_phase2_loading(state_root)
        return 0
    if n == 3:
        from twinbox_core.context_builder import run_phase3_loading

        run_phase3_loading(state_root)
        return 0
    print(f"未知 loading 子命令: {cmd}", file=sys.stderr)
    return 2
