"""Shipped Himalaya release tarballs (Linux x86_64 / aarch64) and lazy extract to state root."""

from __future__ import annotations

import platform
import tarfile
from pathlib import Path


def _linux_machine_alias() -> str | None:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        return "aarch64"
    return None


def bundled_linux_himalaya_tgz() -> Path | None:
    """Return path to the bundled release tarball for this Linux arch, or None."""
    if platform.system() != "Linux":
        return None
    alias = _linux_machine_alias()
    if not alias:
        return None
    here = Path(__file__).resolve().parent / "_bundled" / "himalaya"
    candidate = here / f"himalaya.{alias}-linux.tgz"
    return candidate if candidate.is_file() else None


def materialize_himalaya_from_tgz(tgz_path: Path, dest_bin: Path) -> Path:
    """Extract the top-level ``himalaya`` executable from an official release tarball."""
    dest_bin.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tgz_path, "r:gz") as tf:
        try:
            member = tf.getmember("himalaya")
        except KeyError as exc:
            raise RuntimeError(
                f"{tgz_path.name!s} is missing the top-level 'himalaya' binary entry"
            ) from exc
        reader = tf.extractfile(member)
        if reader is None:
            raise RuntimeError(f"Could not read 'himalaya' from {tgz_path}")
        dest_bin.write_bytes(reader.read())
    dest_bin.chmod(0o755)
    return dest_bin


def try_materialize_bundled_himalaya(state_root: Path) -> Path | None:
    """If a bundle exists for this OS/arch, extract ``himalaya`` into state runtime/bin."""
    tgz = bundled_linux_himalaya_tgz()
    if tgz is None:
        return None
    dest = state_root / "runtime" / "bin" / "himalaya"
    return materialize_himalaya_from_tgz(tgz, dest)
