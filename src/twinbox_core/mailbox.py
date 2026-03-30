"""Mailbox environment resolution, config rendering, and read-only preflight."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .bundled_himalaya import try_materialize_bundled_himalaya
from .env_writer import load_env_file
from .mail_env_contract import (
    OPENCLAW_IMAP_SMTP_ENV_KEYS,
    OPENCLAW_REQUIRES_ENV_KEYS,
    missing_required_mail_values,
)
from .paths import PathResolutionError, resolve_code_root, resolve_existing_dir, resolve_state_root
from .twinbox_config import config_path_for_state_root

OPENCLAW_REQUIRED_ENV = list(OPENCLAW_IMAP_SMTP_ENV_KEYS)
RUNTIME_REQUIRED_ENV = list(OPENCLAW_REQUIRES_ENV_KEYS)

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_IMAP_CONNECTIVITY = 3
EXIT_IMAP_AUTH = 4
EXIT_INTERNAL = 5


@dataclass(frozen=True)
class MailboxPaths:
    code_root: Path
    state_root: Path
    env_file: Path
    config_file: Path
    runtime_dir: Path
    validation_dir: Path
    preflight_json: Path
    imap_sample_json: Path
    stderr_log: Path
    report_file: Path


def resolve_mailbox_paths(
    state_root: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
) -> MailboxPaths:
    if env is None:
        env = os.environ

    code_root = resolve_code_root(resolve_existing_dir(Path(__file__).resolve().parents[2]), env=env)

    if state_root:
        resolved_root = Path(state_root).expanduser().resolve()
    else:
        try:
            resolved_root = resolve_state_root(code_root, env=env)
        except PathResolutionError:
            resolved_root = code_root

    runtime_dir = resolved_root / "runtime" / "himalaya"
    validation_dir = resolved_root / "runtime" / "validation" / "preflight"
    return MailboxPaths(
        code_root=code_root,
        state_root=resolved_root,
        env_file=config_path_for_state_root(resolved_root),
        config_file=runtime_dir / "config.toml",
        runtime_dir=runtime_dir,
        validation_dir=validation_dir,
        preflight_json=validation_dir / "mailbox-smoke.json",
        imap_sample_json=validation_dir / "imap-envelope-sample.json",
        stderr_log=validation_dir / "mailbox-smoke.stderr.log",
        report_file=resolved_root / "docs" / "validation" / "preflight-mailbox-smoke-report.md",
    )



def build_effective_env(
    paths: MailboxPaths,
    env: dict[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    if env is None:
        env = os.environ
    cfg_path = paths.env_file
    legacy_dotenv = cfg_path.parent / ".env"
    config_exists = cfg_path.is_file()
    legacy_exists = legacy_dotenv.is_file()
    file_env = load_env_file(cfg_path)

    effective = dict(file_env)
    effective.update({key: value for key, value in env.items() if value is not None})
    env_sources = {
        "mode": "process-env-first",
        "state_root_env_file": str(cfg_path) if config_exists else (str(legacy_dotenv) if legacy_exists else None),
        "state_root_env_present": "yes" if (config_exists or legacy_exists) else "no",
    }

    defaults_applied: dict[str, str] = {}
    defaults = {
        "MAIL_ACCOUNT_NAME": "myTwinbox",
        "IMAP_ENCRYPTION": "tls",
        "SMTP_ENCRYPTION": "tls",
    }
    for key, value in defaults.items():
        if not effective.get(key):
            effective[key] = value
            defaults_applied[key] = value

    if not effective.get("MAIL_DISPLAY_NAME") and effective.get("MAIL_ACCOUNT_NAME"):
        derived = effective["MAIL_ACCOUNT_NAME"]
        effective["MAIL_DISPLAY_NAME"] = derived
        defaults_applied["MAIL_DISPLAY_NAME"] = derived

    return effective, defaults_applied, file_env, env_sources


def missing_runtime_env(effective_env: dict[str, str]) -> list[str]:
    return missing_required_mail_values(effective_env)


def _account_name(effective_env: dict[str, str], override: str = "") -> str:
    return override or effective_env["MAIL_ACCOUNT_NAME"]


def _mask_value(key: str, value: str) -> str:
    if key.endswith("_PASS"):
        return "<app_password>"
    if key.endswith("_LOGIN") or key == "MAIL_ADDRESS":
        return value or "user@example.com"
    if key.endswith("_HOST"):
        return value or "mail.example.com"
    if key.endswith("_PORT"):
        return value or ("993" if key.startswith("IMAP_") else "465")
    return value or "..."


def render_env_fix_commands(missing_keys: list[str]) -> list[str]:
    if not missing_keys:
        return []
    return [
        f"export {key}={_mask_value(key, '')}"
        for key in missing_keys
    ]


def render_himalaya_config(
    paths: MailboxPaths,
    effective_env: dict[str, str],
) -> Path:
    missing = missing_runtime_env(effective_env)
    if missing:
        raise ValueError(f"Missing required keys for config render: {', '.join(missing)}")

    paths.runtime_dir.mkdir(parents=True, exist_ok=True)

    content = f"""display-name = "{effective_env['MAIL_DISPLAY_NAME']}"
downloads-dir = "{paths.runtime_dir}/downloads"

[accounts.{effective_env['MAIL_ACCOUNT_NAME']}]
email = "{effective_env['MAIL_ADDRESS']}"
default = true
display-name = "{effective_env['MAIL_DISPLAY_NAME']}"

backend.type = "imap"
backend.host = "{effective_env['IMAP_HOST']}"
backend.port = {effective_env['IMAP_PORT']}
backend.encryption.type = "{effective_env['IMAP_ENCRYPTION']}"
backend.login = "{effective_env['IMAP_LOGIN']}"
backend.auth.type = "password"
backend.auth.raw = "{effective_env['IMAP_PASS']}"

message.send.backend.type = "smtp"
message.send.backend.host = "{effective_env['SMTP_HOST']}"
message.send.backend.port = {effective_env['SMTP_PORT']}
message.send.backend.encryption.type = "{effective_env['SMTP_ENCRYPTION']}"
message.send.backend.login = "{effective_env['SMTP_LOGIN']}"
message.send.backend.auth.type = "password"
message.send.backend.auth.raw = "{effective_env['SMTP_PASS']}"
"""
    paths.config_file.write_text(content, encoding="utf-8")
    return paths.config_file


def find_himalaya_binary(paths: MailboxPaths) -> str:
    path_hit = shutil.which("himalaya")
    if path_hit:
        return path_hit
    fallback = paths.state_root / "runtime" / "bin" / "himalaya"
    if fallback.exists() and os.access(fallback, os.X_OK):
        return str(fallback)
    try:
        materialized = try_materialize_bundled_himalaya(paths.state_root)
    except (OSError, RuntimeError, tarfile.TarError) as exc:
        raise FileNotFoundError(
            "himalaya CLI not found; bundled extract failed "
            f"({type(exc).__name__}: {exc})"
        ) from exc
    if materialized is not None and materialized.exists() and os.access(materialized, os.X_OK):
        return str(materialized)
    raise FileNotFoundError(
        f"himalaya CLI not found in PATH, {fallback}, "
        "or a bundled Linux x86_64/aarch64 archive next to twinbox_core"
    )


def classify_imap_failure(stderr_text: str) -> tuple[str, str, str]:
    text = stderr_text.lower()
    if any(token in text for token in [
        "invalid credentials",
        "authentication",
        "auth failed",
        "login failed",
        "username",
        "password",
        "app password",
    ]):
        return (
            "imap_auth_failed",
            "Check IMAP username/password and whether the mailbox requires an app password.",
            "Update IMAP_LOGIN / IMAP_PASS and rerun `twinbox mailbox preflight --json`.",
        )
    if any(token in text for token in [
        "tls",
        "ssl",
        "certificate",
        "starttls",
        "handshake",
        "wrong version number",
        "encryption",
    ]):
        return (
            "imap_tls_failed",
            "Check IMAP port and encryption pairing. Common combinations are 993 + tls or 143 + starttls/plain.",
            "Update IMAP_PORT / IMAP_ENCRYPTION and rerun `twinbox mailbox preflight --json`.",
        )
    if any(token in text for token in [
        "timed out",
        "timeout",
        "connection refused",
        "no route to host",
        "temporary failure in name resolution",
        "name or service not known",
        "network is unreachable",
        "could not resolve",
    ]):
        return (
            "imap_network_failed",
            "Check IMAP host, port, DNS reachability, and firewall/network access from the current runtime.",
            "Update IMAP_HOST / IMAP_PORT or network settings, then rerun `twinbox mailbox preflight --json`.",
        )
    return (
        "imap_command_failed",
        "Inspect the raw IMAP error detail and confirm the mailbox server settings.",
        "Review the stderr detail and rerun `twinbox mailbox preflight --json` after fixing the settings.",
    )


def _preflight_json_payload(
    *,
    login_stage: str,
    status: str,
    effective_env: dict[str, str],
    missing_env: list[str],
    defaults_applied: dict[str, str],
    checks: dict[str, Any],
    actionable_hint: str,
    next_action: str,
    error_code: str | None = None,
    exit_code: int = EXIT_OK,
    paths: MailboxPaths,
) -> dict[str, Any]:
    return {
        "login_mode": "password-env",
        "login_stage": login_stage,
        "status": status,
        "error_code": error_code,
        "exit_code": exit_code,
        "code_root": str(paths.code_root),
        "state_root": str(paths.state_root),
        "env_file": (
            str(paths.env_file)
            if paths.env_file.is_file()
            else (str(paths.env_file.parent / ".env") if (paths.env_file.parent / ".env").is_file() else None)
        ),
        "config_file": str(paths.config_file),
        "required_env": OPENCLAW_REQUIRED_ENV,
        "runtime_required_env": RUNTIME_REQUIRED_ENV,
        "missing_env": missing_env,
        "defaults_applied": defaults_applied,
        "effective_account": effective_env.get("MAIL_ACCOUNT_NAME", ""),
        "checks": checks,
        "actionable_hint": actionable_hint,
        "next_action": next_action,
    }


def format_preflight_text(result: dict[str, Any]) -> str:
    lines = [
        "Mailbox Preflight",
        f"status: {result['status']}",
        f"login_stage: {result['login_stage']}",
    ]
    if result.get("code_root"):
        lines.append(f"code_root: {result['code_root']}")
    if result.get("state_root"):
        lines.append(f"state_root: {result['state_root']}")
    if result.get("env_file"):
        lines.append(f"env_file: {result['env_file']}")

    if result.get("missing_env"):
        lines.append(f"missing_env: {' '.join(result['missing_env'])}")
    if result.get("defaults_applied"):
        applied = ", ".join(f"{key}={value}" for key, value in result["defaults_applied"].items())
        lines.append(f"defaults_applied: {applied}")
    if result.get("env_sources"):
        env_file_mode = result["env_sources"].get("state_root_env_present", "unknown")
        lines.append(f"env_sources: process-env-first, state_root_env={env_file_mode}")

    for name in ("env", "config_render", "imap", "smtp"):
        check = result["checks"].get(name, {})
        status = check.get("status", "unknown")
        detail = check.get("error_code") or check.get("detail")
        lines.append(f"{name}: {status}" + (f" ({detail})" if detail else ""))

    if result.get("actionable_hint"):
        lines.append(f"hint: {result['actionable_hint']}")
    if result.get("next_action"):
        lines.append(f"next_action: {result['next_action']}")

    fix_commands = result["checks"].get("env", {}).get("fix_commands", [])
    if fix_commands:
        lines.append("example_fixes:")
        lines.extend(f"  {command}" for command in fix_commands)

    return "\n".join(lines)


def write_preflight_report(
    *,
    paths: MailboxPaths,
    result: dict[str, Any],
    command: list[str],
) -> None:
    paths.validation_dir.mkdir(parents=True, exist_ok=True)
    paths.report_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().isoformat()
    report_lines = [
        "# Preflight Mailbox Smoke Report",
        "",
        f"- time: {timestamp}",
        f"- login_stage: {result['login_stage']}",
        f"- status: {result['status']}",
        f"- error_code: {result.get('error_code') or 'none'}",
        f"- preflight_json: {paths.preflight_json.relative_to(paths.state_root)}",
        f"- stderr_log: {paths.stderr_log.relative_to(paths.state_root)}",
        f"- imap_sample_json: {paths.imap_sample_json.relative_to(paths.state_root)}",
        "",
        "## Command",
        "",
        "```bash",
        " ".join(command),
        "```",
        "",
        "## Result",
        "",
        "```json",
        json.dumps(result, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Notes",
        "",
        "- This preflight renders himalaya config and performs a read-only IMAP envelope list.",
        "- SMTP is reported as a warning in read-only mode and is not used to block Phase 1-4.",
    ]
    paths.report_file.write_text("\n".join(report_lines) + "\n", encoding="utf-8")


def run_preflight(
    *,
    state_root: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
    account_override: str = "",
    folder: str = "INBOX",
    page_size: int = 5,
) -> tuple[int, dict[str, Any]]:
    if env is None:
        env = os.environ
    paths = resolve_mailbox_paths(state_root=state_root, env=env)
    effective_env, defaults_applied, _, env_sources = build_effective_env(paths, env=env)
    missing = missing_runtime_env(effective_env)

    env_check: dict[str, Any] = {
        "status": "success" if not missing else "fail",
        "missing_env": missing,
        "fix_commands": render_env_fix_commands(missing),
    }
    config_check: dict[str, Any] = {"status": "pending"}
    imap_check: dict[str, Any] = {"status": "pending"}
    smtp_check: dict[str, Any] = {
        "status": "warn",
        "error_code": "smtp_skipped_read_only",
        "detail": "SMTP connectivity/auth is not enforced in read-only mode.",
    }

    if missing:
        result = _preflight_json_payload(
            login_stage="unconfigured",
            status="fail",
            effective_env=effective_env,
            missing_env=missing,
            defaults_applied=defaults_applied,
            checks={
                "env": env_check,
                "config_render": {"status": "skipped"},
                "imap": {"status": "skipped"},
                "smtp": smtp_check,
            },
            actionable_hint="Provide the missing mailbox settings before validating the account.",
            next_action="Set the missing environment variables and rerun `twinbox mailbox preflight --json`.",
            error_code="missing_env",
            exit_code=EXIT_CONFIG,
            paths=paths,
        )
        result["env_sources"] = env_sources
        return EXIT_CONFIG, result

    try:
        config_path = render_himalaya_config(paths, effective_env)
        config_check = {"status": "success", "config_file": str(config_path)}
    except Exception as exc:  # pragma: no cover - defensive guard
        result = _preflight_json_payload(
            login_stage="unconfigured",
            status="fail",
            effective_env=effective_env,
            missing_env=[],
            defaults_applied=defaults_applied,
            checks={
                "env": env_check,
                "config_render": {"status": "fail", "error_code": "config_render_failed", "detail": str(exc)},
                "imap": {"status": "skipped"},
                "smtp": smtp_check,
            },
            actionable_hint="The mailbox config could not be rendered. Check the resolved host/port/account values.",
            next_action="Fix the mailbox settings and rerun `twinbox mailbox preflight --json`.",
            error_code="config_render_failed",
            exit_code=EXIT_CONFIG,
            paths=paths,
        )
        result["env_sources"] = env_sources
        return EXIT_CONFIG, result

    paths.validation_dir.mkdir(parents=True, exist_ok=True)
    paths.stderr_log.write_text("", encoding="utf-8")

    try:
        himalaya_bin = find_himalaya_binary(paths)
    except FileNotFoundError as exc:
        result = _preflight_json_payload(
            login_stage="validated",
            status="fail",
            effective_env=effective_env,
            missing_env=[],
            defaults_applied=defaults_applied,
            checks={
                "env": env_check,
                "config_render": config_check,
                "imap": {"status": "fail", "error_code": "himalaya_missing", "detail": str(exc)},
                "smtp": smtp_check,
            },
            actionable_hint=(
                "Install himalaya, place the binary at runtime/bin/himalaya, or use Linux x86_64/aarch64 "
                "where a bundled release tarball ships with twinbox_core."
            ),
            next_action="Install the CLI (or use a bundled platform) and rerun `twinbox mailbox preflight --json`.",
            error_code="himalaya_missing",
            exit_code=EXIT_INTERNAL,
            paths=paths,
        )
        result["env_sources"] = env_sources
        return EXIT_INTERNAL, result

    if os.environ.get("TWINBOX_IMAP_POOL", "").strip() in ("1", "true", "yes"):
        from twinbox_core import imap_pool as _imap_pool

        ok_sel, sel_detail = _imap_pool.imap_probe_select_folder(effective_env, folder)
        if ok_sel:
            paths.imap_sample_json.write_text(
                json.dumps(
                    {"mode": "imap_pool", "folder": folder, "detail": sel_detail},
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            imap_check = {
                "status": "success",
                "sample_path": str(paths.imap_sample_json),
                "folder": folder,
                "page_size": page_size,
                "mode": "imap_pool",
            }
            command = ["imap_pool", sel_detail]
            result = _preflight_json_payload(
                login_stage="mailbox-connected",
                status="warn",
                effective_env=effective_env,
                missing_env=[],
                defaults_applied=defaults_applied,
                checks={
                    "env": env_check,
                    "config_render": config_check,
                    "imap": imap_check,
                    "smtp": smtp_check,
                },
                actionable_hint="Mailbox read-only preflight passed (IMAP pool). SMTP is not blocking in read-only mode.",
                next_action="Run `twinbox-orchestrate run` (full pipeline) or `twinbox-orchestrate run --phase 1` to start the read-only pipeline.",
                error_code="smtp_skipped_read_only",
                exit_code=EXIT_OK,
                paths=paths,
            )
            result["env_sources"] = env_sources
            write_preflight_report(paths=paths, result=result, command=command)
            paths.preflight_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return EXIT_OK, result

    command = [
        himalaya_bin,
        "-c",
        str(paths.config_file),
        "envelope",
        "list",
        "--account",
        _account_name(effective_env, account_override),
        "--folder",
        folder,
        "--page",
        "1",
        "--page-size",
        str(page_size),
        "--output",
        "json",
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    paths.stderr_log.write_text(completed.stderr or "", encoding="utf-8")

    if completed.returncode != 0:
        error_code, hint, next_action = classify_imap_failure(completed.stderr or "")
        exit_code = EXIT_IMAP_AUTH if error_code == "imap_auth_failed" else EXIT_IMAP_CONNECTIVITY
        imap_check = {
            "status": "fail",
            "error_code": error_code,
            "detail": (completed.stderr or "").strip(),
            "command": command,
        }
        result = _preflight_json_payload(
            login_stage="validated",
            status="fail",
            effective_env=effective_env,
            missing_env=[],
            defaults_applied=defaults_applied,
            checks={
                "env": env_check,
                "config_render": config_check,
                "imap": imap_check,
                "smtp": smtp_check,
            },
            actionable_hint=hint,
            next_action=next_action,
            error_code=error_code,
            exit_code=exit_code,
            paths=paths,
        )
        result["env_sources"] = env_sources
        write_preflight_report(paths=paths, result=result, command=command)
        paths.preflight_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return exit_code, result

    paths.imap_sample_json.write_text(completed.stdout, encoding="utf-8")
    imap_check = {
        "status": "success",
        "sample_path": str(paths.imap_sample_json),
        "folder": folder,
        "page_size": page_size,
    }
    result = _preflight_json_payload(
        login_stage="mailbox-connected",
        status="warn",
        effective_env=effective_env,
        missing_env=[],
        defaults_applied=defaults_applied,
        checks={
            "env": env_check,
            "config_render": config_check,
            "imap": imap_check,
            "smtp": smtp_check,
        },
        actionable_hint="Mailbox read-only preflight passed. SMTP is not blocking in read-only mode.",
        next_action="Run `twinbox-orchestrate run` (full pipeline) or `twinbox-orchestrate run --phase 1` to start the read-only pipeline.",
        error_code="smtp_skipped_read_only",
        exit_code=EXIT_OK,
        paths=paths,
    )
    result["env_sources"] = env_sources
    write_preflight_report(paths=paths, result=result, command=command)
    paths.preflight_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return EXIT_OK, result


def cmd_check_env(args: argparse.Namespace) -> int:
    paths = resolve_mailbox_paths(state_root=args.state_root)
    effective_env, defaults_applied, _, _ = build_effective_env(paths)
    missing = missing_runtime_env(effective_env)

    if missing:
        for key in missing:
            print(f"Missing required key: {key}")
        print("")
        print("Example fixes:")
        for command in render_env_fix_commands(missing):
            print(command)
        return 1

    if defaults_applied:
        print("Applied defaults:")
        for key, value in defaults_applied.items():
            print(f"  {key}={value}")
    print("All required mailbox settings are present.")
    return 0


def cmd_render_config(args: argparse.Namespace) -> int:
    paths = resolve_mailbox_paths(state_root=args.state_root)
    effective_env, defaults_applied, _, _ = build_effective_env(paths)

    missing = missing_runtime_env(effective_env)
    if missing:
        for key in missing:
            print(f"Missing required key: {key}", file=sys.stderr)
        return 1

    config_path = render_himalaya_config(paths, effective_env)
    if defaults_applied:
        print("Applied defaults:")
        for key, value in defaults_applied.items():
            print(f"  {key}={value}")
    print(f"Rendered {config_path}")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    exit_code, result = run_preflight(
        state_root=args.state_root,
        account_override=args.account,
        folder=args.folder,
        page_size=args.page_size,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_preflight_text(result))
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_env = subparsers.add_parser("check-env", help="Validate mailbox env/defaults")
    check_env.add_argument("--state-root", help="Override twinbox state root")

    render = subparsers.add_parser("render-config", help="Render himalaya config")
    render.add_argument("--state-root", help="Override twinbox state root")

    preflight = subparsers.add_parser("preflight", help="Run read-only mailbox preflight")
    preflight.add_argument("--state-root", help="Override twinbox state root")
    preflight.add_argument("--account", default="", help="Override MAIL_ACCOUNT_NAME")
    preflight.add_argument("--folder", default="INBOX", help="Folder for envelope list")
    preflight.add_argument("--page-size", default=5, type=int, help="Envelope list page size")
    preflight.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "check-env":
            return cmd_check_env(args)
        if args.command == "render-config":
            return cmd_render_config(args)
        if args.command == "preflight":
            return cmd_preflight(args)
    except Exception as exc:  # pragma: no cover - defensive CLI fallback
        print(str(exc), file=sys.stderr)
        return EXIT_INTERNAL

    parser.error(f"Unknown command: {args.command}")
    return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
