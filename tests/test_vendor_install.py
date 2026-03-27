"""Tests for twinbox_core.vendor_sync and twinbox vendor CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from twinbox_core.vendor_sync import install_vendor, vendor_manifest_path, vendor_status, vendor_twinbox_core_path


def _fake_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    pkg = repo / "src" / "twinbox_core"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("# pkg\n", encoding="utf-8")
    (pkg / "task_cli.py").write_text("# stub\n", encoding="utf-8")
    (pkg / "stub.py").write_text("VALUE = 42\n", encoding="utf-8")
    return repo


def _env(repo_root: Path, state_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["TWINBOX_STATE_ROOT"] = str(state_root)
    twinbox_src = Path(__file__).resolve().parents[1] / "src"
    env["PYTHONPATH"] = str(twinbox_src) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def test_install_vendor_copies_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "state"
    state.mkdir()
    repo = _fake_repo(tmp_path)
    monkeypatch.chdir(repo)

    result = install_vendor(state_root=state, code_root=repo, dry_run=False)
    assert result["installed"] is True
    dest = vendor_twinbox_core_path(state)
    assert (dest / "__init__.py").is_file()
    assert (dest / "stub.py").read_text(encoding="utf-8").strip() == "VALUE = 42"

    mp = vendor_manifest_path(state)
    assert mp.is_file()
    manifest = json.loads(mp.read_text(encoding="utf-8"))
    assert "installed_at" in manifest
    assert manifest["source_code_root"] == str(repo.resolve())
    assert isinstance(manifest.get("file_count"), int)
    assert manifest["file_count"] >= 2
    assert "twinbox_version" in manifest


def test_install_vendor_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "state"
    state.mkdir()
    repo = _fake_repo(tmp_path)
    monkeypatch.chdir(repo)

    result = install_vendor(state_root=state, code_root=repo, dry_run=True)
    assert result["dry_run"] is True
    assert not vendor_twinbox_core_path(state).exists()


def test_vendor_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "state"
    state.mkdir()
    repo = _fake_repo(tmp_path)
    monkeypatch.chdir(repo)
    install_vendor(state_root=state, code_root=repo, dry_run=False)

    st = vendor_status(state)
    assert st["package_present"] is True
    assert st["file_count_py"] >= 2
    assert st.get("integrity_ok") is True
    assert st["file_count"] >= 2
    assert st["manifest_present"] is True
    assert st["manifest"] is not None
    assert st["manifest"].get("source_code_root")


def test_install_missing_source_raises(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    repo = tmp_path / "empty_repo"
    repo.mkdir()
    with pytest.raises(FileNotFoundError):
        install_vendor(state_root=state, code_root=repo, dry_run=False)


def test_cli_vendor_install_and_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = tmp_path / "state"
    state.mkdir()
    repo = _fake_repo(tmp_path)
    monkeypatch.chdir(repo)
    env = _env(repo, state)

    r = subprocess.run(
        [sys.executable, "-m", "twinbox_core.task_cli", "vendor", "install", "--json"],
        env=env,
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["ok"] is True
    assert data["installed"] is True

    r2 = subprocess.run(
        [sys.executable, "-m", "twinbox_core.task_cli", "vendor", "status", "--json"],
        env=env,
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r2.returncode == 0, r2.stderr
    body = json.loads(r2.stdout)
    assert body["package_present"] is True
