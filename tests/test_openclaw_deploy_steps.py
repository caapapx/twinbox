"""Unit tests for openclaw_deploy_steps (narrow, no full deploy orchestration)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from twinbox_core.openclaw_deploy_runtime import OpenClawDeployRuntime, SubprocessCommandRunner
from twinbox_core.openclaw_deploy_steps import (
    RollbackContext,
    append_step,
    fail_step,
    remove_skill_dir_step,
    skill_canonical_path,
    strip_openclaw_json_step,
)
from twinbox_core.openclaw_deploy_types import OpenClawDeployReport


class _MemFileOps:
    """Minimal FileOpsPort for step-level tests."""

    def __init__(self, files: dict[Path, str] | None = None) -> None:
        self.files = {Path(k): v for k, v in (files or {}).items()}
        self.write_json_calls: list[tuple[Path, dict[str, Any]]] = []
        self.dirs: set[Path] = set()

    def is_file(self, path: Path) -> bool:
        return Path(path) in self.files

    def is_dir(self, path: Path) -> bool:
        return Path(path) in self.dirs

    def read_text(self, path: Path, *, encoding: str = "utf-8") -> str:
        del encoding
        p = Path(path)
        if p not in self.files:
            raise FileNotFoundError(p)
        return self.files[p]

    def write_json_atomic(self, path: Path, data: dict[str, Any]) -> None:
        p = Path(path)
        self.write_json_calls.append((p, data))
        self.files[p] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def test_skill_canonical_path(tmp_path: Path) -> None:
    sr = tmp_path / "state"
    sr.mkdir()
    assert skill_canonical_path(sr) == (sr / "SKILL.md").resolve()


def test_append_step_and_fail_step() -> None:
    report = OpenClawDeployReport(ok=True)
    append_step(report, "a", "ok", "m1", {"k": 1})
    assert report.ok is True
    assert len(report.steps) == 1
    assert report.steps[0].id == "a" and report.steps[0].detail == {"k": 1}

    fail_step(report, "b", "oops", {"e": 2})
    assert report.ok is False
    assert len(report.steps) == 2
    assert report.steps[1].id == "b" and report.steps[1].status == "failed"


def _rollback_ctx(tmp_path: Path, *, dry_run: bool) -> RollbackContext:
    oc = tmp_path / ".openclaw"
    return RollbackContext(
        openclaw_home=oc,
        openclaw_json=oc / "openclaw.json",
        skill_dir=oc / "skills" / "twinbox",
        config_path=tmp_path / ".config" / "twinbox",
        dry_run=dry_run,
        restart_gateway=False,
        remove_config=False,
        openclaw_bin="openclaw",
    )


def test_strip_openclaw_json_step_invalid_json_fails(tmp_path: Path) -> None:
    oc = tmp_path / ".openclaw"
    p = oc / "openclaw.json"
    ops = _MemFileOps({p: "{"})
    rt = OpenClawDeployRuntime(file_ops=ops, command_runner=SubprocessCommandRunner())
    report = OpenClawDeployReport(ok=True)
    ctx = _rollback_ctx(tmp_path, dry_run=False)

    ok = strip_openclaw_json_step(ctx, report, rt)
    assert ok is False
    assert report.ok is False
    assert report.steps[-1].id == "strip_openclaw_json"
    assert report.steps[-1].status == "failed"


def test_strip_openclaw_json_step_dry_run_skips_write(tmp_path: Path) -> None:
    oc = tmp_path / ".openclaw"
    p = oc / "openclaw.json"
    cfg = {"skills": {"entries": {"twinbox": {"enabled": True}}}}
    ops = _MemFileOps({p: json.dumps(cfg)})
    rt = OpenClawDeployRuntime(file_ops=ops, command_runner=SubprocessCommandRunner())
    report = OpenClawDeployReport(ok=True)
    ctx = _rollback_ctx(tmp_path, dry_run=True)

    ok = strip_openclaw_json_step(ctx, report, rt)
    assert ok is True
    assert report.ok is True
    assert ops.write_json_calls == []
    step = next(s for s in report.steps if s.id == "strip_openclaw_json")
    assert step.status == "dry_run"
    assert step.detail.get("had_twinbox_entry") is True


def test_strip_openclaw_json_step_removes_twinbox_entry(tmp_path: Path) -> None:
    oc = tmp_path / ".openclaw"
    p = oc / "openclaw.json"
    cfg = {
        "skills": {"entries": {"twinbox": {"x": 1}, "keep": {"y": 2}}},
        "meta": 3,
    }
    ops = _MemFileOps({p: json.dumps(cfg)})
    rt = OpenClawDeployRuntime(file_ops=ops, command_runner=SubprocessCommandRunner())
    report = OpenClawDeployReport(ok=True)
    ctx = _rollback_ctx(tmp_path, dry_run=False)

    ok = strip_openclaw_json_step(ctx, report, rt)
    assert ok is True
    assert len(ops.write_json_calls) == 1
    written = ops.write_json_calls[0][1]
    assert "twinbox" not in written.get("skills", {}).get("entries", {})
    assert written["skills"]["entries"]["keep"]["y"] == 2
    assert written["meta"] == 3


def test_remove_skill_dir_step_dry_run_no_remove(tmp_path: Path) -> None:
    oc = tmp_path / ".openclaw"
    skill_dir = oc / "skills" / "twinbox"
    ops = _MemFileOps()
    ops.dirs.add(skill_dir)
    rt = OpenClawDeployRuntime(file_ops=ops, command_runner=SubprocessCommandRunner())
    report = OpenClawDeployReport(ok=True)
    ctx = _rollback_ctx(tmp_path, dry_run=True)

    ok = remove_skill_dir_step(ctx, report, rt)
    assert ok is True
    step = next(s for s in report.steps if s.id == "remove_skill_dir")
    assert step.status == "dry_run"
    assert step.detail.get("exists") is True
