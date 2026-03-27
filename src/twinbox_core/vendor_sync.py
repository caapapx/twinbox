"""Copy twinbox_core package into state_root/vendor for host-only Python path."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

MANIFEST_NAME = "MANIFEST.json"


def vendor_root(state_root: Path) -> Path:
    return state_root / "vendor"


def vendor_twinbox_core_path(state_root: Path) -> Path:
    return vendor_root(state_root) / "twinbox_core"


def vendor_manifest_path(state_root: Path) -> Path:
    return vendor_root(state_root) / MANIFEST_NAME


def _ignore_copy(_dir: str, names: list[str]) -> list[str]:
    return [n for n in names if n == "__pycache__" or n.endswith((".pyc", ".pyo"))]


def _git_rev(code_root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(code_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return None
        line = (proc.stdout or "").strip()
        return line or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def install_vendor(
    *,
    state_root: Path,
    code_root: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync ``code_root/src/twinbox_core`` into ``state_root/vendor/twinbox_core`` and write MANIFEST."""
    src = (code_root / "src" / "twinbox_core").resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"source package not found: {src}")

    vr = vendor_root(state_root)
    dest_pkg = vendor_twinbox_core_path(state_root)
    manifest_path = vendor_manifest_path(state_root)

    result: dict[str, Any] = {
        "dry_run": dry_run,
        "source": str(src),
        "destination": str(dest_pkg),
        "manifest_path": str(manifest_path),
    }

    if dry_run:
        result["would_install"] = True
        return result

    vr.mkdir(parents=True, exist_ok=True)
    vr.chmod(0o700)

    if dest_pkg.exists():
        shutil.rmtree(dest_pkg)
    shutil.copytree(src, dest_pkg, ignore=_ignore_copy)

    git_rev = _git_rev(code_root)
    manifest: dict[str, Any] = {
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "source_code_root": str(code_root.resolve()),
    }
    if git_rev:
        manifest["git_rev"] = git_rev

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    result["installed"] = True
    result["manifest"] = manifest
    return result


def _count_py_files(root: Path) -> int:
    n = 0
    if not root.is_dir():
        return 0
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        n += 1
    return n


def vendor_status(state_root: Path) -> dict[str, Any]:
    """Describe current vendor layout under state_root."""
    vr = vendor_root(state_root)
    pkg = vendor_twinbox_core_path(state_root)
    mp = vendor_manifest_path(state_root)

    manifest: dict[str, Any] | None = None
    if mp.is_file():
        try:
            manifest = json.loads(mp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = None

    pkg_exists = pkg.is_dir() and (pkg / "__init__.py").is_file()
    mtime: float | None = None
    if pkg_exists:
        try:
            mtime = pkg.stat().st_mtime
        except OSError:
            mtime = None

    return {
        "state_root": str(state_root.resolve()),
        "vendor_root": str(vr),
        "twinbox_core_path": str(pkg),
        "package_present": pkg_exists,
        "file_count_py": _count_py_files(pkg) if pkg_exists else 0,
        "manifest_present": mp.is_file(),
        "manifest": manifest,
        "directory_mtime": mtime,
    }
