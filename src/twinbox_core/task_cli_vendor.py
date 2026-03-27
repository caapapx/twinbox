"""`twinbox vendor` subcommands — sync package copy under state_root/vendor."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from twinbox_core.paths import PathResolutionError, resolve_code_root, resolve_state_root
from twinbox_core.vendor_sync import install_vendor, vendor_status


def register_vendor_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    v = subparsers.add_parser("vendor", help="Sync twinbox_core into state_root/vendor for PYTHONPATH-only hosts")
    v_sub = v.add_subparsers(dest="vendor_command", required=True)

    ins = v_sub.add_parser("install", help="Copy src/twinbox_core from code root into $TWINBOX_STATE_ROOT/vendor")
    ins.add_argument("--dry-run", action="store_true", help="Print planned paths without writing")
    ins.add_argument("--json", action="store_true", help="Emit JSON result")

    st = v_sub.add_parser("status", help="Show vendor directory and MANIFEST state")
    st.add_argument("--json", action="store_true", help="Emit machine-readable JSON")


def _roots() -> tuple[Path, Path]:
    cwd = Path.cwd()
    try:
        code_root = resolve_code_root(cwd)
        state_root = resolve_state_root(cwd)
    except PathResolutionError as exc:
        raise RuntimeError(str(exc)) from exc
    return code_root, state_root


def dispatch_vendor(args: argparse.Namespace) -> int:
    try:
        code_root, state_root = _roots()
    except RuntimeError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if args.vendor_command == "install":
        dry = getattr(args, "dry_run", False)
        json_out = getattr(args, "json", False)
        try:
            result = install_vendor(state_root=state_root, code_root=code_root, dry_run=dry)
        except FileNotFoundError as exc:
            if json_out:
                print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
            else:
                print(f"错误: {exc}", file=sys.stderr)
            return 1
        if json_out:
            out = {"ok": True, **result}
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            if dry:
                print(f"dry-run: would copy {result['source']} -> {result['destination']}")
            else:
                print(f"installed: {result['destination']}")
                print(f"manifest: {result['manifest_path']}")
        return 0

    if args.vendor_command == "status":
        body = vendor_status(state_root)
        if getattr(args, "json", False):
            print(json.dumps(body, ensure_ascii=False, indent=2))
        else:
            print("package_present:", body["package_present"])
            print("integrity_ok:", body.get("integrity_ok"))
            print("path:", body["twinbox_core_path"])
            print("files:", body.get("file_count"))
            print("py_files:", body["file_count_py"])
            print("manifest_present:", body["manifest_present"])
            if body.get("manifest"):
                print("installed_at:", body["manifest"].get("installed_at", ""))
        return 0

    print(f"未知 vendor 子命令: {args.vendor_command}", file=sys.stderr)
    return 2
