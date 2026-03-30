"""Phase 1 incremental (daytime) sync: env check, himalaya folder list, imap_incremental, optional full-load fallback."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from twinbox_core.imap_incremental import EXIT_FALLBACK
from twinbox_core.mailbox import (
    build_effective_env,
    find_himalaya_binary,
    missing_runtime_env,
    render_env_fix_commands,
    render_himalaya_config,
    resolve_mailbox_paths,
)
from twinbox_core.paths import resolve_state_root


def _merge_subprocess_env(paths, effective_env: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env["TWINBOX_CODE_ROOT"] = str(paths.code_root)
    env["TWINBOX_STATE_ROOT"] = str(paths.state_root)
    env["TWINBOX_CANONICAL_ROOT"] = str(paths.state_root)
    for key, value in effective_env.items():
        if value is not None and str(value) != "":
            env[str(key)] = str(value)
    return env


def _resolve_state_root_arg(raw: str) -> Path:
    if raw.strip():
        return Path(raw).expanduser().resolve()
    for key in ("TWINBOX_STATE_ROOT", "TWINBOX_CANONICAL_ROOT"):
        v = os.environ.get(key, "").strip()
        if v:
            return Path(v).expanduser().resolve()
    return resolve_state_root(Path.cwd())


def run_incremental_sync(
    state_root: Path,
    *,
    account_override: str = "",
    folder_filter: str = "",
    max_pages_per_folder: int = 20,
    page_size: int = 50,
    sample_body_count: int = 30,
    lookback_days: int | None = None,
) -> int:
    paths = resolve_mailbox_paths(state_root=str(state_root))
    effective_env, _, _, _ = build_effective_env(paths)
    missing = missing_runtime_env(effective_env)
    if missing:
        for key in missing:
            print(f"Missing required key: {key}")
        print("")
        print("Example fixes:")
        for command in render_env_fix_commands(missing):
            print(command)
        return 1

    render_himalaya_config(paths, effective_env)
    try:
        himalaya_bin = find_himalaya_binary(paths)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    account = account_override or effective_env.get("MAIL_ACCOUNT_NAME", "myTwinbox")
    mail_address = (effective_env.get("MAIL_ADDRESS") or "").strip()
    if not mail_address:
        print("Missing MAIL_ADDRESS after mailbox validation.", file=sys.stderr)
        return 1

    raw_dir = paths.state_root / "runtime" / "context" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    folders_json = raw_dir / "folders.json"
    config_file = paths.config_file

    subprocess_env = _merge_subprocess_env(paths, effective_env)

    print("Fetching folder list for incremental sync...")
    with folders_json.open("w", encoding="utf-8") as handle:
        completed = subprocess.run(
            [
                himalaya_bin,
                "-c",
                str(config_file),
                "folder",
                "list",
                "--account",
                account,
                "--output",
                "json",
            ],
            stdout=handle,
            stderr=subprocess.PIPE,
            text=True,
            env=subprocess_env,
            check=False,
        )
    if completed.returncode != 0:
        err = getattr(completed, "stderr", None) or ""
        if err:
            print(err, file=sys.stderr)
        return completed.returncode

    if folder_filter.strip():
        payload = [{"name": folder_filter.strip()}]
        folders_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if lookback_days is None:
        raw_lb = os.environ.get("PIPELINE_LOOKBACK_DAYS", "").strip()
        lookback_days = int(raw_lb) if raw_lb.isdigit() else 7

    argv = [
        sys.executable,
        "-m",
        "twinbox_core.imap_incremental",
        "--state-root",
        str(paths.state_root),
        "--folders-json",
        str(folders_json),
        "--account",
        account,
        "--config",
        str(config_file),
        "--himalaya-bin",
        himalaya_bin,
        "--sample-body-count",
        str(sample_body_count),
        "--lookback-days",
        str(lookback_days),
    ]
    inc = subprocess.run(argv, env=subprocess_env, check=False)
    if inc.returncode == EXIT_FALLBACK:
        print("Incremental sync requested full fallback; running phase1 loading_pipeline...")
        fb = [
            sys.executable,
            "-m",
            "twinbox_core.loading_pipeline",
            "phase1",
            "--state-root",
            str(paths.state_root),
            "--account",
            account,
            "--max-pages-per-folder",
            str(max_pages_per_folder),
            "--page-size",
            str(page_size),
            "--sample-body-count",
            str(sample_body_count),
            "--lookback-days",
            str(lookback_days),
        ]
        if folder_filter.strip():
            fb += ["--folder", folder_filter.strip()]
        return subprocess.run(fb, env=subprocess_env, check=False).returncode

    return inc.returncode


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", default="", help="Twinbox state root (default: env or resolve cwd)")
    parser.add_argument("--account", default="", help="Override MAIL_ACCOUNT_NAME")
    parser.add_argument("--folder", default="", help="Only scan one folder (default: all)")
    parser.add_argument("--max-pages-per-folder", type=int, default=20)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--sample-body-count", type=int, default=30)
    parser.add_argument("--lookback-days", type=int, default=-1, help="Default: PIPELINE_LOOKBACK_DAYS or 7")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    state_root = _resolve_state_root_arg(args.state_root)
    lb = None if args.lookback_days < 0 else args.lookback_days
    return run_incremental_sync(
        state_root,
        account_override=args.account,
        folder_filter=args.folder,
        max_pages_per_folder=args.max_pages_per_folder,
        page_size=args.page_size,
        sample_body_count=args.sample_body_count,
        lookback_days=lb,
    )


if __name__ == "__main__":
    raise SystemExit(main())
