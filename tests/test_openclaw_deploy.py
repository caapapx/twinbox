"""Tests for OpenClaw host deploy orchestration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from twinbox_core.openclaw_deploy import (
    load_openclaw_json,
    merge_twinbox_openclaw_entry,
    run_openclaw_deploy,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_merge_preserves_other_skill_entries() -> None:
    base = {
        "skills": {"entries": {"other": {"enabled": True, "env": {"X": "1"}}}},
        "gateway": {"token": "keep"},
    }
    merged = merge_twinbox_openclaw_entry(
        base,
        dotenv={"IMAP_HOST": "imap.example.com", "IMAP_PORT": "993"},
        sync_env_from_dotenv=True,
    )
    assert merged["gateway"]["token"] == "keep"
    assert merged["skills"]["entries"]["other"]["enabled"] is True
    tb = merged["skills"]["entries"]["twinbox"]
    assert tb["enabled"] is True
    assert tb["env"]["IMAP_HOST"] == "imap.example.com"
    assert tb["env"]["IMAP_PORT"] == "993"


def test_merge_no_env_sync_keeps_existing_twinbox_env() -> None:
    base = {
        "skills": {
            "entries": {
                "twinbox": {
                    "enabled": False,
                    "env": {"IMAP_HOST": "old.example.com"},
                }
            }
        }
    }
    merged = merge_twinbox_openclaw_entry(
        base,
        dotenv={"IMAP_HOST": "from.dotenv"},
        sync_env_from_dotenv=False,
    )
    twin = merged["skills"]["entries"]["twinbox"]
    assert twin["enabled"] is True
    assert twin["env"]["IMAP_HOST"] == "old.example.com"


def test_load_openclaw_json_missing_returns_empty(tmp_path: Path) -> None:
    assert load_openclaw_json(tmp_path / "nope.json") == {}


def test_load_openclaw_json_invalid_raises(tmp_path: Path) -> None:
    p = tmp_path / "openclaw.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_openclaw_json(p)


def test_run_openclaw_deploy_dry_run_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    oc = tmp_path / ".openclaw"
    report = run_openclaw_deploy(
        code_root=REPO_ROOT,
        openclaw_home=oc,
        dry_run=True,
        restart_gateway=True,
        sync_env_from_dotenv=False,
    )
    assert report.ok
    ids = [s.id for s in report.steps]
    assert "bootstrap_roots" in ids
    assert "merge_openclaw_json" in ids
    assert "sync_skill_md" in ids
    assert "gateway_restart" in ids
    assert not (oc / "openclaw.json").exists()


def _fake_run_ok(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def _run_real_init_fake_openclaw(
    cmd: list[str], **kwargs: object
) -> subprocess.CompletedProcess[str]:
    """Run the real roots init script; stub `openclaw gateway restart` only."""
    if len(cmd) >= 3 and cmd[0] == "openclaw" and cmd[1] == "gateway":
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    return subprocess.run(cmd, **kwargs)


def test_run_openclaw_deploy_applies_files_no_gateway_restart_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    oc = tmp_path / ".openclaw"
    report = run_openclaw_deploy(
        code_root=REPO_ROOT,
        openclaw_home=oc,
        dry_run=False,
        restart_gateway=False,
        sync_env_from_dotenv=False,
        run_subprocess=_run_real_init_fake_openclaw,
    )
    assert report.ok
    skill = oc / "skills" / "twinbox" / "SKILL.md"
    assert skill.is_file()
    cfg = json.loads((oc / "openclaw.json").read_text(encoding="utf-8"))
    assert cfg["skills"]["entries"]["twinbox"]["enabled"] is True


def test_run_openclaw_deploy_missing_skill_md_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cr = tmp_path / "empty"
    cr.mkdir()
    (cr / "scripts").mkdir()
    (cr / "scripts" / "install_openclaw_twinbox_init.sh").write_text("#!/bin/bash\nexit 0\n")
    sr = tmp_path / "state"
    sr.mkdir()
    cfg = tmp_path / ".config" / "twinbox"
    cfg.mkdir(parents=True)
    (cfg / "code-root").write_text(str(cr.resolve()) + "\n")
    (cfg / "state-root").write_text(str(sr.resolve()) + "\n")

    report = run_openclaw_deploy(
        code_root=cr,
        openclaw_home=tmp_path / ".openclaw",
        dry_run=True,
        restart_gateway=False,
        sync_env_from_dotenv=False,
    )
    assert not report.ok
    assert any(s.id == "sync_skill_md" and s.status == "failed" for s in report.steps)
