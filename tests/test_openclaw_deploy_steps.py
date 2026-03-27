"""Unit tests for openclaw_deploy_steps (narrow, no full deploy orchestration)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from twinbox_core.openclaw_deploy_runtime import OpenClawDeployRuntime, SubprocessCommandRunner
from twinbox_core.openclaw_json_io import default_openclaw_fragment_path
from twinbox_core.openclaw_deploy_steps import (
    DeployContext,
    RollbackContext,
    append_step,
    fail_step,
    gateway_restart_step,
    merge_openclaw_json_step,
    remove_skill_dir_step,
    skill_canonical_path,
    strip_openclaw_json_step,
    sync_skill_md_step,
)
from twinbox_core.openclaw_deploy_types import OpenClawDeployReport


class _MemFileOps:
    """Minimal FileOpsPort for step-level tests."""

    def __init__(self, files: dict[Path, str] | None = None) -> None:
        self.files = {Path(k): v for k, v in (files or {}).items()}
        self.write_json_calls: list[tuple[Path, dict[str, Any]]] = []
        self.dirs: set[Path] = set()
        self.mkdir_calls: list[Path] = []
        self.copy_calls: list[tuple[Path, Path]] = []
        self.unlink_calls: list[Path] = []
        self.symlink_calls: list[tuple[Path, Path]] = []

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

    def mkdir(self, path: Path, *, parents: bool = True, exist_ok: bool = True) -> None:
        del parents, exist_ok
        p = Path(path)
        cur = p
        while cur != cur.parent:
            self.dirs.add(cur)
            cur = cur.parent
        self.mkdir_calls.append(p)

    def copy_file(self, src: Path, dst: Path) -> None:
        sp, dp = Path(src), Path(dst)
        if sp not in self.files:
            raise FileNotFoundError(sp)
        self.mkdir(dp.parent)
        self.files[dp] = self.files[sp]
        self.copy_calls.append((sp, dp))

    def unlink(self, path: Path) -> None:
        p = Path(path)
        self.unlink_calls.append(p)
        self.files.pop(p, None)

    def symlink(self, target: Path, link_path: Path) -> None:
        tp, lp = Path(target), Path(link_path)
        if tp not in self.files:
            raise FileNotFoundError(tp)
        self.mkdir(lp.parent)
        self.files[lp] = self.files[tp]
        self.symlink_calls.append((tp, lp))

    def remove_tree(self, path: Path) -> None:
        raise NotImplementedError


class _MemFileOpsSymlinkFails(_MemFileOps):
    """First symlink raises; used to assert copy_fallback path."""

    def symlink(self, target: Path, link_path: Path) -> None:
        del target, link_path
        raise OSError("simulated symlink unsupported")


class _RecordingCommandRunner:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[tuple[list[str], Path]] = []

    def run(
        self, argv: list[str], *, cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), Path(cwd)))
        return subprocess.CompletedProcess(
            argv, self.returncode, stdout="", stderr=self.stderr
        )


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


def _deploy_ctx(
    tmp_path: Path,
    *,
    dry_run: bool = False,
    fragment_path: Path | None = None,
    no_fragment: bool = False,
) -> DeployContext:
    code_root = tmp_path / "repo"
    state_root = tmp_path / "state"
    oc = tmp_path / ".openclaw"
    return DeployContext(
        code_root=code_root,
        openclaw_home=oc,
        openclaw_json=oc / "openclaw.json",
        state_root=state_root,
        skill_src=code_root / "SKILL.md",
        skill_dest=oc / "skills" / "twinbox" / "SKILL.md",
        init_script=code_root / "scripts" / "install_openclaw_twinbox_init.sh",
        dry_run=dry_run,
        restart_gateway=False,
        sync_env_from_dotenv=False,
        strict=False,
        fragment_path=fragment_path,
        no_fragment=no_fragment,
        openclaw_bin="openclaw",
    )


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


def test_merge_openclaw_json_step_no_fragment_skips_merge_fragment(tmp_path: Path) -> None:
    oc = tmp_path / ".openclaw"
    host = oc / "openclaw.json"
    ops = _MemFileOps({host: "{}"})
    rt = OpenClawDeployRuntime(file_ops=ops, command_runner=SubprocessCommandRunner())
    report = OpenClawDeployReport(ok=True)
    ctx = _deploy_ctx(tmp_path, dry_run=False, no_fragment=True)

    ok = merge_openclaw_json_step(
        ctx, report, rt, dotenv={}, missing_required=[]
    )
    assert ok is True
    frag_step = next(s for s in report.steps if s.id == "merge_openclaw_fragment")
    assert frag_step.status == "skipped"
    assert "--no-fragment" in frag_step.message
    assert ops.write_json_calls
    assert "skills" in ops.write_json_calls[0][1]


def test_merge_openclaw_json_step_explicit_fragment_missing_fails(tmp_path: Path) -> None:
    oc = tmp_path / ".openclaw"
    host = oc / "openclaw.json"
    missing = tmp_path / "nowhere.fragment.json"
    ops = _MemFileOps({host: "{}"})
    rt = OpenClawDeployRuntime(file_ops=ops, command_runner=SubprocessCommandRunner())
    report = OpenClawDeployReport(ok=True)
    ctx = _deploy_ctx(tmp_path, fragment_path=missing)

    ok = merge_openclaw_json_step(
        ctx, report, rt, dotenv={}, missing_required=[]
    )
    assert ok is False
    assert report.steps[-1].id == "merge_openclaw_fragment"
    assert report.steps[-1].status == "failed"
    assert ops.write_json_calls == []


def test_merge_openclaw_json_step_explicit_fragment_deep_merges(tmp_path: Path) -> None:
    oc = tmp_path / ".openclaw"
    host = oc / "openclaw.json"
    frag = tmp_path / "extra.fragment.json"
    existing = {"top": {"keep": 1}, "skills": {"entries": {"keep_skill": {"a": 1}}}}
    fragment = {"top": {"from_frag": 2}, "only_in_frag": True}
    ops = _MemFileOps(
        {
            host: json.dumps(existing),
            frag: json.dumps(fragment),
        }
    )
    rt = OpenClawDeployRuntime(file_ops=ops, command_runner=SubprocessCommandRunner())
    report = OpenClawDeployReport(ok=True)
    ctx = _deploy_ctx(tmp_path, fragment_path=frag)

    ok = merge_openclaw_json_step(
        ctx, report, rt, dotenv={}, missing_required=[]
    )
    assert ok is True
    frag_step = next(s for s in report.steps if s.id == "merge_openclaw_fragment")
    assert frag_step.status == "ok"
    assert frag_step.detail.get("explicit") is True
    written = ops.write_json_calls[0][1]
    assert written["top"]["keep"] == 1
    assert written["top"]["from_frag"] == 2
    assert written["only_in_frag"] is True
    assert written["skills"]["entries"]["keep_skill"]["a"] == 1
    assert written["skills"]["entries"]["twinbox"]["enabled"] is True


def test_merge_openclaw_json_step_optional_default_fragment_skipped_when_absent(
    tmp_path: Path,
) -> None:
    oc = tmp_path / ".openclaw"
    host = oc / "openclaw.json"
    ops = _MemFileOps({host: "{}"})
    rt = OpenClawDeployRuntime(file_ops=ops, command_runner=SubprocessCommandRunner())
    report = OpenClawDeployReport(ok=True)
    ctx = _deploy_ctx(tmp_path)

    ok = merge_openclaw_json_step(
        ctx, report, rt, dotenv={}, missing_required=[]
    )
    assert ok is True
    frag_step = next(s for s in report.steps if s.id == "merge_openclaw_fragment")
    assert frag_step.status == "skipped"
    assert "optional" in frag_step.message
    expected = default_openclaw_fragment_path(ctx.code_root)
    assert str(expected) in frag_step.message


def test_merge_openclaw_json_step_default_fragment_from_code_root(tmp_path: Path) -> None:
    oc = tmp_path / ".openclaw"
    host = oc / "openclaw.json"
    ctx = _deploy_ctx(tmp_path)
    default_frag = default_openclaw_fragment_path(ctx.code_root)
    ops = _MemFileOps(
        {
            host: json.dumps({"base_only": True}),
            default_frag: json.dumps({"from_default_fragment": 1}),
        }
    )
    rt = OpenClawDeployRuntime(file_ops=ops, command_runner=SubprocessCommandRunner())
    report = OpenClawDeployReport(ok=True)

    ok = merge_openclaw_json_step(
        ctx, report, rt, dotenv={}, missing_required=[]
    )
    assert ok is True
    frag_step = next(s for s in report.steps if s.id == "merge_openclaw_fragment")
    assert frag_step.status == "ok"
    assert frag_step.detail.get("explicit") is False
    written = ops.write_json_calls[0][1]
    assert written["base_only"] is True
    assert written["from_default_fragment"] == 1


def test_merge_openclaw_json_step_fragment_invalid_json_fails(tmp_path: Path) -> None:
    oc = tmp_path / ".openclaw"
    host = oc / "openclaw.json"
    frag = tmp_path / "bad.json"
    ops = _MemFileOps(
        {
            host: "{}",
            frag: "{",
        }
    )
    rt = OpenClawDeployRuntime(file_ops=ops, command_runner=SubprocessCommandRunner())
    report = OpenClawDeployReport(ok=True)
    ctx = _deploy_ctx(tmp_path, fragment_path=frag)

    ok = merge_openclaw_json_step(
        ctx, report, rt, dotenv={}, missing_required=[]
    )
    assert ok is False
    assert report.steps[-1].id == "merge_openclaw_fragment"
    assert report.steps[-1].status == "failed"
    assert ops.write_json_calls == []


def test_merge_openclaw_json_step_dry_run_merges_fragment_but_skips_write(
    tmp_path: Path,
) -> None:
    oc = tmp_path / ".openclaw"
    host = oc / "openclaw.json"
    frag = tmp_path / "f.json"
    ops = _MemFileOps(
        {
            host: "{}",
            frag: json.dumps({"x": 1}),
        }
    )
    rt = OpenClawDeployRuntime(file_ops=ops, command_runner=SubprocessCommandRunner())
    report = OpenClawDeployReport(ok=True)
    ctx = _deploy_ctx(tmp_path, dry_run=True, fragment_path=frag)

    ok = merge_openclaw_json_step(
        ctx, report, rt, dotenv={}, missing_required=[]
    )
    assert ok is True
    frag_step = next(s for s in report.steps if s.id == "merge_openclaw_fragment")
    assert frag_step.status == "dry_run"
    json_step = next(s for s in report.steps if s.id == "merge_openclaw_json")
    assert json_step.status == "dry_run"
    assert ops.write_json_calls == []


def test_sync_skill_md_step_missing_skill_fails(tmp_path: Path) -> None:
    ctx = _deploy_ctx(tmp_path, dry_run=False)
    ops = _MemFileOps()
    rt = OpenClawDeployRuntime(
        file_ops=ops, command_runner=SubprocessCommandRunner()
    )
    report = OpenClawDeployReport(ok=True)

    ok = sync_skill_md_step(ctx, report, rt)
    assert ok is False
    assert report.steps[-1].id == "sync_skill_md"
    assert report.steps[-1].status == "failed"


def test_sync_skill_md_step_dry_run(tmp_path: Path) -> None:
    ctx = _deploy_ctx(tmp_path, dry_run=True)
    skill = ctx.skill_src
    ops = _MemFileOps({skill: "---\nname: twinbox\n---\n"})
    rt = OpenClawDeployRuntime(
        file_ops=ops, command_runner=SubprocessCommandRunner()
    )
    report = OpenClawDeployReport(ok=True)

    ok = sync_skill_md_step(ctx, report, rt)
    assert ok is True
    assert ops.copy_calls == []
    step = next(s for s in report.steps if s.id == "sync_skill_md")
    assert step.status == "dry_run"
    assert str(skill_canonical_path(ctx.state_root)) in step.message


def test_sync_skill_md_step_symlink_ok(tmp_path: Path) -> None:
    ctx = _deploy_ctx(tmp_path, dry_run=False)
    skill = ctx.skill_src
    body = "---\nname: twinbox\n---\nbody"
    ops = _MemFileOps({skill: body})
    rt = OpenClawDeployRuntime(
        file_ops=ops, command_runner=SubprocessCommandRunner()
    )
    report = OpenClawDeployReport(ok=True)

    ok = sync_skill_md_step(ctx, report, rt)
    assert ok is True
    canon = skill_canonical_path(ctx.state_root)
    assert ops.files.get(canon) == body
    assert ops.files.get(ctx.skill_dest) == body
    assert ops.symlink_calls and ops.symlink_calls[0][0] == canon
    step = next(s for s in report.steps if s.id == "sync_skill_md")
    assert step.detail.get("mode") == "symlink"


def test_sync_skill_md_step_copy_fallback_when_symlink_fails(tmp_path: Path) -> None:
    ctx = _deploy_ctx(tmp_path, dry_run=False)
    skill = ctx.skill_src
    body = "x"
    ops = _MemFileOpsSymlinkFails({skill: body})
    rt = OpenClawDeployRuntime(
        file_ops=ops, command_runner=SubprocessCommandRunner()
    )
    report = OpenClawDeployReport(ok=True)

    ok = sync_skill_md_step(ctx, report, rt)
    assert ok is True
    canon = skill_canonical_path(ctx.state_root)
    assert ops.files.get(ctx.skill_dest) == body
    assert ops.symlink_calls == []
    assert len([c for c in ops.copy_calls if c[1] == ctx.skill_dest]) == 1
    step = next(s for s in report.steps if s.id == "sync_skill_md")
    assert step.detail.get("mode") == "copy_fallback"
    assert "symlink_error" in step.detail


def test_gateway_restart_step_skipped_when_disabled() -> None:
    runner = _RecordingCommandRunner()
    rt = OpenClawDeployRuntime(file_ops=_MemFileOps(), command_runner=runner)
    report = OpenClawDeployReport(ok=True)
    cwd = Path("/tmp/x")

    ok = gateway_restart_step(
        restart_gateway=False,
        dry_run=False,
        openclaw_bin="openclaw",
        cwd=cwd,
        report=report,
        runtime=rt,
    )
    assert ok is True
    assert runner.calls == []
    step = next(s for s in report.steps if s.id == "gateway_restart")
    assert step.status == "skipped"


def test_gateway_restart_step_dry_run() -> None:
    runner = _RecordingCommandRunner()
    rt = OpenClawDeployRuntime(file_ops=_MemFileOps(), command_runner=runner)
    report = OpenClawDeployReport(ok=True)
    cwd = Path("/tmp/x")

    ok = gateway_restart_step(
        restart_gateway=True,
        dry_run=True,
        openclaw_bin="oc",
        cwd=cwd,
        report=report,
        runtime=rt,
    )
    assert ok is True
    assert runner.calls == []
    step = next(s for s in report.steps if s.id == "gateway_restart")
    assert step.status == "dry_run"


def test_gateway_restart_step_ok() -> None:
    runner = _RecordingCommandRunner()
    rt = OpenClawDeployRuntime(file_ops=_MemFileOps(), command_runner=runner)
    report = OpenClawDeployReport(ok=True)
    cwd = Path("/tmp/x")

    ok = gateway_restart_step(
        restart_gateway=True,
        dry_run=False,
        openclaw_bin="oc",
        cwd=cwd,
        report=report,
        runtime=rt,
    )
    assert ok is True
    assert runner.calls == [(["oc", "gateway", "restart"], cwd)]
    assert next(s for s in report.steps if s.id == "gateway_restart").status == "ok"


def test_gateway_restart_step_nonzero_fails() -> None:
    runner = _RecordingCommandRunner(returncode=1, stderr="err")
    rt = OpenClawDeployRuntime(file_ops=_MemFileOps(), command_runner=runner)
    report = OpenClawDeployReport(ok=True)
    cwd = Path("/tmp/x")

    ok = gateway_restart_step(
        restart_gateway=True,
        dry_run=False,
        openclaw_bin="oc",
        cwd=cwd,
        report=report,
        runtime=rt,
    )
    assert ok is False
    assert report.ok is False
    step = next(s for s in report.steps if s.id == "gateway_restart")
    assert step.status == "failed"
    assert "err" in (step.detail.get("stderr") or "")


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
