"""Tests for shipped Himalaya Linux bundles and extract-to-state-root."""

from __future__ import annotations

import io
import platform
import tarfile
from pathlib import Path

import pytest

from twinbox_core.bundled_himalaya import (
    bundled_linux_himalaya_tgz,
    materialize_himalaya_from_tgz,
    try_materialize_bundled_himalaya,
)


def _tiny_himalaya_tgz() -> bytes:
    script = b"#!/bin/sh\necho himalaya-test-ok\n"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="himalaya")
        info.size = len(script)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(script))
    return buf.getvalue()


def test_materialize_himalaya_from_tgz_writes_executable(tmp_path: Path) -> None:
    tgz_path = tmp_path / "himalaya.fake.tgz"
    tgz_path.write_bytes(_tiny_himalaya_tgz())
    dest = tmp_path / "bin" / "himalaya"
    materialize_himalaya_from_tgz(tgz_path, dest)
    assert dest.is_file()
    assert dest.stat().st_mode & 0o111
    text = dest.read_bytes()
    assert b"himalaya-test-ok" in text


def test_materialize_himalaya_from_tgz_missing_member_raises(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"x"
        info = tarfile.TarInfo(name="other")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    tgz_path = tmp_path / "bad.tgz"
    tgz_path.write_bytes(buf.getvalue())
    with pytest.raises(RuntimeError, match="missing"):
        materialize_himalaya_from_tgz(tgz_path, tmp_path / "himalaya")


@pytest.mark.skipif(platform.system() != "Linux", reason="bundled archives target Linux only")
def test_bundled_linux_tarball_shipped_for_current_arch() -> None:
    p = bundled_linux_himalaya_tgz()
    assert p is not None, "expected a bundled tgz on supported Linux arches"
    assert p.is_file(), f"missing bundled archive: {p}"


@pytest.mark.skipif(platform.system() != "Linux", reason="bundled archives target Linux only")
def test_try_materialize_produces_runnable_binary(tmp_path: Path) -> None:
    if bundled_linux_himalaya_tgz() is None:
        pytest.skip("no bundle for this Linux machine()")
    dest = try_materialize_bundled_himalaya(tmp_path)
    assert dest is not None
    assert dest.name == "himalaya"
    import subprocess

    out = subprocess.run([str(dest), "--version"], capture_output=True, text=True, check=False)
    assert out.returncode == 0
    assert "himalaya" in (out.stdout + out.stderr).lower()
