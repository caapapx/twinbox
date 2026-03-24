"""Shared path resolution for twinbox."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


class PathResolutionError(RuntimeError):
    """Raised when twinbox cannot resolve a stable code/state root."""


def config_dir(env: dict[str, str] | None = None) -> Path:
    env = env or os.environ
    return Path(env.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "twinbox"


def canonical_root_file(env: dict[str, str] | None = None) -> Path:
    env = env or os.environ
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


def resolve_canonical_root(
    code_root: str | os.PathLike[str],
    env: dict[str, str] | None = None,
) -> Path:
    env = env or os.environ
    resolved_code_root = resolve_existing_dir(code_root)

    candidate = env.get("TWINBOX_CANONICAL_ROOT", "")
    if not candidate:
        config_file = canonical_root_file(env)
        if config_file.is_file():
            candidate = _read_first_line(config_file)

    if candidate:
        try:
            return resolve_existing_dir(candidate)
        except PathResolutionError as exc:
            raise PathResolutionError(
                f"Configured canonical root does not exist: {candidate}"
            ) from exc

    return resolved_code_root


def init_roots(
    script_path: str | os.PathLike[str],
    env: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    script_dir = resolve_existing_dir(Path(script_path).parent)
    code_root = resolve_existing_dir(script_dir / "..")
    canonical_root = resolve_canonical_root(code_root, env=env)
    return code_root, canonical_root


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("config-dir")
    subparsers.add_parser("canonical-root-file")

    resolve_dir = subparsers.add_parser("resolve-existing-dir")
    resolve_dir.add_argument("candidate")

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
        elif args.command == "canonical-root-file":
            print(canonical_root_file())
        elif args.command == "resolve-existing-dir":
            print(resolve_existing_dir(args.candidate))
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
