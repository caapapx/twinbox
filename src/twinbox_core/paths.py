"""Shared code/state root resolution for twinbox."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


class PathResolutionError(RuntimeError):
    """Raised when twinbox cannot resolve a stable code/state root."""


def config_dir(env: dict[str, str] | None = None) -> Path:
    if env is None:
        env = os.environ
    return Path(env.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "twinbox"


def code_root_file(env: dict[str, str] | None = None) -> Path:
    if env is None:
        env = os.environ
    override = env.get("TWINBOX_CODE_ROOT_FILE")
    if override:
        return Path(override).expanduser()
    return config_dir(env) / "code-root"


def state_root_file(env: dict[str, str] | None = None) -> Path:
    if env is None:
        env = os.environ
    override = env.get("TWINBOX_STATE_ROOT_FILE")
    if override:
        return Path(override).expanduser()
    return config_dir(env) / "state-root"


def canonical_root_file(env: dict[str, str] | None = None) -> Path:
    """Legacy compatibility file for state-root lookup."""
    if env is None:
        env = os.environ
    override = env.get("TWINBOX_CANONICAL_ROOT_FILE")
    if override:
        return Path(override).expanduser()
    return config_dir(env) / "canonical-root"


def resolve_existing_dir(candidate: str | os.PathLike[str] | None) -> Path:
    if not candidate:
        raise PathResolutionError("Missing directory candidate")

    resolved = Path(candidate).expanduser()
    try:
        return resolved.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PathResolutionError(f"Configured path does not exist: {candidate}") from exc
    except OSError as exc:
        raise PathResolutionError(f"Unable to resolve path: {candidate}") from exc


def _read_first_line(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return lines[0].strip() if lines else ""


def _configured_root_candidate(
    *,
    env: dict[str, str],
    env_names: tuple[str, ...],
    file_candidates: tuple[Path, ...],
) -> str:
    for env_name in env_names:
        candidate = env.get(env_name, "").strip()
        if candidate:
            return candidate

    for path in file_candidates:
        if path.is_file():
            candidate = _read_first_line(path)
            if candidate:
                return candidate

    return ""


def resolve_code_root(
    default_code_root: str | os.PathLike[str],
    env: dict[str, str] | None = None,
) -> Path:
    if env is None:
        env = os.environ
    resolved_default = resolve_existing_dir(default_code_root)
    candidate = _configured_root_candidate(
        env=env,
        env_names=("TWINBOX_CODE_ROOT",),
        file_candidates=(code_root_file(env),),
    )
    if not candidate:
        return resolved_default
    try:
        return resolve_existing_dir(candidate)
    except PathResolutionError as exc:
        raise PathResolutionError(f"Configured code root does not exist: {candidate}") from exc


def resolve_state_root(
    default_state_root: str | os.PathLike[str],
    env: dict[str, str] | None = None,
) -> Path:
    if env is None:
        env = os.environ
    resolved_default = resolve_existing_dir(default_state_root)
    candidate = _configured_root_candidate(
        env=env,
        env_names=("TWINBOX_STATE_ROOT", "TWINBOX_CANONICAL_ROOT"),
        file_candidates=(state_root_file(env), canonical_root_file(env)),
    )
    if not candidate:
        return resolved_default
    try:
        return resolve_existing_dir(candidate)
    except PathResolutionError as exc:
        raise PathResolutionError(f"Configured state root does not exist: {candidate}") from exc


def resolve_canonical_root(
    code_root: str | os.PathLike[str],
    env: dict[str, str] | None = None,
) -> Path:
    """Legacy alias for resolve_state_root()."""
    return resolve_state_root(code_root, env=env)


def init_roots(
    script_path: str | os.PathLike[str],
    env: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    script_dir = resolve_existing_dir(Path(script_path).parent)
    default_code_root = resolve_existing_dir(script_dir / "..")
    code_root = resolve_code_root(default_code_root, env=env)
    state_root = resolve_state_root(code_root, env=env)
    return code_root, state_root


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("config-dir")
    subparsers.add_parser("code-root-file")
    subparsers.add_parser("state-root-file")
    subparsers.add_parser("canonical-root-file")

    resolve_dir = subparsers.add_parser("resolve-existing-dir")
    resolve_dir.add_argument("candidate")

    resolve_code = subparsers.add_parser("resolve-code-root")
    resolve_code.add_argument("default_code_root")

    resolve_state = subparsers.add_parser("resolve-state-root")
    resolve_state.add_argument("default_state_root")

    resolve_root = subparsers.add_parser("resolve-canonical-root")
    resolve_root.add_argument("code_root")

    init = subparsers.add_parser("init-roots")
    init.add_argument("script_path")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "config-dir":
            print(config_dir())
        elif args.command == "code-root-file":
            print(code_root_file())
        elif args.command == "state-root-file":
            print(state_root_file())
        elif args.command == "canonical-root-file":
            print(canonical_root_file())
        elif args.command == "resolve-existing-dir":
            print(resolve_existing_dir(args.candidate))
        elif args.command == "resolve-code-root":
            print(resolve_code_root(args.default_code_root))
        elif args.command == "resolve-state-root":
            print(resolve_state_root(args.default_state_root))
        elif args.command == "resolve-canonical-root":
            print(resolve_canonical_root(args.code_root))
        elif args.command == "init-roots":
            code_root, canonical_root = init_roots(args.script_path)
            print(code_root)
            print(canonical_root)
        else:
            parser.error(f"unknown command: {args.command}")
    except PathResolutionError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
