"""`twinbox loading` — Python entrypoints that delegate to ``scripts/phase*_loading.sh``."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from twinbox_core.paths import PathResolutionError, resolve_code_root


def register_loading_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    load = subparsers.add_parser(
        "loading",
        help="Phase mailbox loading (invokes repo scripts/phaseN_loading.sh)",
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
        code_root = resolve_code_root(cwd)
    except PathResolutionError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    script = code_root / "scripts" / f"phase{n}_loading.sh"
    if not script.is_file():
        print(f"错误: 未找到 {script}", file=sys.stderr)
        return 1
    extra = list(getattr(args, "script_args", []) or [])
    if extra and extra[0] == "--":
        extra = extra[1:]
    r = subprocess.run(["bash", str(script), *extra], cwd=str(code_root))
    return r.returncode if r.returncode is not None else 1
