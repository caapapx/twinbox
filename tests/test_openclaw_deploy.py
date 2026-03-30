"""Tests for OpenClaw host deploy orchestration."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

from twinbox_core.openclaw_deploy import (
    apply_openclaw_plugin_vendor_cwd,
    deep_merge_openclaw,
    load_openclaw_json,
    merge_twinbox_openclaw_entry,
    remove_twinbox_skill_entry_from_openclaw,
    run_openclaw_deploy,
    run_openclaw_rollback,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class _FakeFileOps:
    def __init__(
        self,
        *,
        files: dict[Path, str] | None = None,
        dirs: set[Path] | None = None,
    ) -> None:
        self.files = {Path(path): text for path, text in (files or {}).items()}
        self.dirs = {Path(path) for path in (dirs or set())}
        self.write_json_calls: list[tuple[Path, dict[str, Any]]] = []
        self.copy_calls: list[tuple[Path, Path]] = []
        self.symlink_calls: list[tuple[Path, Path]] = []
        self.unlink_calls: list[Path] = []
        self.remove_tree_calls: list[Path] = []
        self.mkdir_calls: list[Path] = []

    def is_file(self, path: Path) -> bool:
        return Path(path) in self.files

    def is_dir(self, path: Path) -> bool:
        candidate = Path(path)
        return candidate in self.dirs

    def read_text(self, path: Path, *, encoding: str = "utf-8") -> str:
        del encoding
        candidate = Path(path)
        if candidate not in self.files:
            raise FileNotFoundError(candidate)
        return self.files[candidate]

    def mkdir(self, path: Path, *, parents: bool = True, exist_ok: bool = True) -> None:
        del parents, exist_ok
        candidate = Path(path)
        current = candidate
        while current != current.parent:
            self.dirs.add(current)
            current = current.parent
        self.dirs.add(current)
        self.mkdir_calls.append(candidate)

    def write_json_atomic(self, path: Path, data: dict[str, Any]) -> None:
        candidate = Path(path)
        self.mkdir(candidate.parent)
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        self.files[candidate] = text
        self.write_json_calls.append((candidate, data))

    def copy_file(self, src: Path, dst: Path) -> None:
        src_path = Path(src)
        dst_path = Path(dst)
        if src_path not in self.files:
            raise FileNotFoundError(src_path)
        self.mkdir(dst_path.parent)
        self.files[dst_path] = self.files[src_path]
        self.copy_calls.append((src_path, dst_path))

    def unlink(self, path: Path) -> None:
        candidate = Path(path)
        self.unlink_calls.append(candidate)
        self.files.pop(candidate, None)

    def symlink(self, target: Path, link_path: Path) -> None:
        tp = Path(target)
        lp = Path(link_path)
        self.symlink_calls.append((tp, lp))
        self.mkdir(lp.parent)
        if tp not in self.files:
            raise FileNotFoundError(tp)
        self.files[lp] = self.files[tp]

    def remove_tree(self, path: Path) -> None:
        candidate = Path(path)
        self.remove_tree_calls.append(candidate)
        self.dirs = {existing for existing in self.dirs if existing != candidate}
        self.files = {
            existing: text
            for existing, text in self.files.items()
            if existing != candidate and candidate not in existing.parents
        }


class _FakeCommandRunner:
    def __init__(
        self,
        *,
        results: dict[tuple[str, ...], subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.results = results or {}
        self.calls: list[tuple[list[str], Path]] = []

    def run(self, argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), Path(cwd)))
        key = tuple(argv)
        if key in self.results:
            return self.results[key]
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class _FakeRuntime:
    def __init__(self, *, file_ops: _FakeFileOps, command_runner: _FakeCommandRunner) -> None:
        self.file_ops = file_ops
        self.command_runner = command_runner


def _make_runtime_layout(
    tmp_path: Path,
    *,
    dotenv_lines: str = "",
    openclaw_json: dict[str, Any] | None = None,
) -> tuple[Path, Path, Path, _FakeRuntime]:
    code_root = tmp_path / "repo"
    code_root.mkdir()
    state_root = tmp_path / "state"
    state_root.mkdir()
    (state_root / ".env").write_text(dotenv_lines, encoding="utf-8")
    openclaw_home = tmp_path / ".openclaw"

    init_script = code_root / "scripts" / "install_openclaw_twinbox_init.sh"
    skill_src = code_root / "SKILL.md"
    files = {
        init_script: "#!/bin/bash\nexit 0\n",
        skill_src: "---\nname: twinbox\n---\n",
    }
    if openclaw_json is not None:
        files[openclaw_home / "openclaw.json"] = (
            json.dumps(openclaw_json, ensure_ascii=False, indent=2) + "\n"
        )
    dirs = {
        code_root / "scripts",
        openclaw_home,
        openclaw_home / "skills",
        openclaw_home / "skills" / "twinbox",
    }

    file_ops = _FakeFileOps(files=files, dirs=dirs)
    command_runner = _FakeCommandRunner(
        results={
            ("bash", str(init_script)): subprocess.CompletedProcess(
                ["bash", str(init_script)], 0, stdout="ok\n", stderr=""
            )
        }
    )
    return code_root, state_root, openclaw_home, _FakeRuntime(
        file_ops=file_ops,
        command_runner=command_runner,
    )


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


def test_deep_merge_openclaw_recurses_dicts_replaces_lists() -> None:
    dst = {"skills": {"entries": {"a": 1}}, "x": [1, 2]}
    src = {"skills": {"entries": {"b": 2}}, "x": [3]}
    out = deep_merge_openclaw(dst, src)
    assert out["skills"]["entries"] == {"a": 1, "b": 2}
    assert out["x"] == [3]


def test_merge_order_fragment_then_twinbox() -> None:
    existing = {"skills": {"entries": {"keep": {"enabled": True}}}}
    frag = {"plugins": {"allow": ["twinbox-task-tools"]}}
    base = deep_merge_openclaw(existing, frag)
    merged = merge_twinbox_openclaw_entry(
        base, dotenv={}, sync_env_from_dotenv=False
    )
    assert merged["plugins"]["allow"] == ["twinbox-task-tools"]
    assert "twinbox" in merged["skills"]["entries"]
    assert "keep" in merged["skills"]["entries"]


def test_explicit_fragment_missing_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    report = run_openclaw_deploy(
        code_root=REPO_ROOT,
        openclaw_home=tmp_path / ".openclaw",
        dry_run=True,
        restart_gateway=False,
        sync_env_from_dotenv=False,
        fragment_path=tmp_path / "missing-fragment.json",
        no_fragment=False,
    )
    assert not report.ok
    assert any(
        s.id == "merge_openclaw_fragment" and s.status == "failed" for s in report.steps
    )


def test_remove_twinbox_skill_entry_preserves_other_entries() -> None:
    base = {
        "skills": {
            "entries": {
                "twinbox": {"enabled": True},
                "other": {"enabled": False},
            }
        },
        "gateway": {"x": 1},
    }
    out, had = remove_twinbox_skill_entry_from_openclaw(base)
    assert had is True
    assert "twinbox" not in out["skills"]["entries"]
    assert out["skills"]["entries"]["other"]["enabled"] is False
    assert out["gateway"]["x"] == 1


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


def test_run_openclaw_deploy_strict_fails_when_mail_env_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    report = run_openclaw_deploy(
        code_root=REPO_ROOT,
        openclaw_home=tmp_path / ".openclaw",
        dry_run=True,
        restart_gateway=False,
        sync_env_from_dotenv=True,
        strict=True,
    )
    assert not report.ok
    failed = [s for s in report.steps if s.id == "merge_openclaw_json" and s.status == "failed"]
    assert failed
    assert "IMAP_HOST" in failed[0].message


def test_run_openclaw_deploy_runtime_strict_avoids_write_side_effects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code_root, state_root, openclaw_home, runtime = _make_runtime_layout(tmp_path)
    monkeypatch.setenv("TWINBOX_CODE_ROOT", str(code_root.resolve()))
    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))

    report = run_openclaw_deploy(
        code_root=code_root,
        openclaw_home=openclaw_home,
        dry_run=False,
        restart_gateway=True,
        sync_env_from_dotenv=True,
        strict=True,
        runtime=runtime,
        skip_bridge=True,
    )

    assert not report.ok
    assert [step.id for step in report.steps] == [
        "bootstrap_roots",
        "merge_openclaw_json",
    ]
    assert runtime.file_ops.write_json_calls == []
    assert runtime.file_ops.copy_calls == []
    assert runtime.command_runner.calls == [
        (["bash", str(code_root / "scripts" / "install_openclaw_twinbox_init.sh")], code_root)
    ]


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
    assert "ensure_himalaya" in ids
    assert "sync_skill_md" in ids
    assert "gateway_restart" in ids
    assert not (oc / "openclaw.json").exists()


def test_run_openclaw_deploy_runtime_dry_run_keeps_side_effects_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code_root, state_root, openclaw_home, runtime = _make_runtime_layout(tmp_path)
    monkeypatch.setenv("TWINBOX_CODE_ROOT", str(code_root.resolve()))
    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))

    report = run_openclaw_deploy(
        code_root=code_root,
        openclaw_home=openclaw_home,
        dry_run=True,
        restart_gateway=True,
        sync_env_from_dotenv=False,
        runtime=runtime,
        skip_bridge=True,
    )

    assert report.ok
    assert [step.id for step in report.steps] == [
        "bootstrap_roots",
        "merge_openclaw_fragment",
        "merge_openclaw_json",
        "ensure_himalaya",
        "sync_skill_md",
        "gateway_restart",
        "openclaw_prerequisite_bundle",
    ]
    assert runtime.file_ops.write_json_calls == []
    assert runtime.file_ops.copy_calls == []
    assert runtime.command_runner.calls == []


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


def test_run_openclaw_deploy_skill_sync_fallback_when_symlink_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code_root, state_root, openclaw_home, runtime_ok = _make_runtime_layout(tmp_path)
    monkeypatch.setenv("TWINBOX_CODE_ROOT", str(code_root.resolve()))
    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))

    class _Ops(_FakeFileOps):
        def symlink(self, target: Path, link_path: Path) -> None:
            raise OSError("symlink unsupported")

    fo = _Ops(files=dict(runtime_ok.file_ops.files), dirs=set(runtime_ok.file_ops.dirs))
    runtime = _FakeRuntime(file_ops=fo, command_runner=runtime_ok.command_runner)

    report = run_openclaw_deploy(
        code_root=code_root,
        openclaw_home=openclaw_home,
        dry_run=False,
        restart_gateway=False,
        sync_env_from_dotenv=False,
        runtime=runtime,
        skip_bridge=True,
    )
    assert report.ok
    step = next(s for s in report.steps if s.id == "sync_skill_md")
    assert step.detail.get("mode") == "copy_fallback"
    canonical = (state_root / "SKILL.md").resolve()
    oc_skill = openclaw_home / "skills" / "twinbox" / "SKILL.md"
    assert fo.copy_calls[0] == (code_root / "SKILL.md", canonical)
    assert fo.copy_calls[1] == (canonical, oc_skill)


def test_run_openclaw_deploy_runtime_restart_failure_keeps_prior_steps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code_root, state_root, openclaw_home, runtime = _make_runtime_layout(tmp_path)
    monkeypatch.setenv("TWINBOX_CODE_ROOT", str(code_root.resolve()))
    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))
    runtime.command_runner.results[("openclaw", "gateway", "restart")] = subprocess.CompletedProcess(
        ["openclaw", "gateway", "restart"], 1, stdout="", stderr="boom\n"
    )

    report = run_openclaw_deploy(
        code_root=code_root,
        openclaw_home=openclaw_home,
        dry_run=False,
        restart_gateway=True,
        sync_env_from_dotenv=False,
        runtime=runtime,
        skip_bridge=True,
    )

    assert not report.ok
    assert [step.id for step in report.steps] == [
        "bootstrap_roots",
        "merge_openclaw_fragment",
        "merge_openclaw_json",
        "ensure_himalaya",
        "sync_skill_md",
        "gateway_restart",
    ]
    assert runtime.file_ops.write_json_calls
    canonical = (state_root / "SKILL.md").resolve()
    assert runtime.file_ops.copy_calls == [(code_root / "SKILL.md", canonical)]
    assert runtime.file_ops.symlink_calls == [
        (canonical, openclaw_home / "skills" / "twinbox" / "SKILL.md")
    ]
    cfg = runtime.file_ops.write_json_calls[0][1]
    assert cfg["skills"]["entries"]["twinbox"]["enabled"] is True
    assert runtime.command_runner.calls[-1] == (
        ["openclaw", "gateway", "restart"],
        code_root,
    )


def test_run_openclaw_rollback_removes_json_and_skill_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    oc = tmp_path / ".openclaw"
    oc.mkdir(parents=True)
    cfg = {"skills": {"entries": {"twinbox": {"enabled": True, "env": {}}}}}
    (oc / "openclaw.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    sd = oc / "skills" / "twinbox"
    sd.mkdir(parents=True)
    (sd / "SKILL.md").write_text("---\nname: twinbox\n---\n", encoding="utf-8")

    report = run_openclaw_rollback(
        openclaw_home=oc,
        dry_run=False,
        restart_gateway=False,
        remove_config=False,
        run_subprocess=_fake_run_ok,
    )
    assert report.ok
    data = json.loads((oc / "openclaw.json").read_text(encoding="utf-8"))
    assert "twinbox" not in data.get("skills", {}).get("entries", {})
    assert not sd.exists()


def test_run_openclaw_rollback_remove_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    cfg_dir = tmp_path / ".config" / "twinbox"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "code-root").write_text("/tmp/x\n", encoding="utf-8")
    oc = tmp_path / ".openclaw"
    oc.mkdir(parents=True)
    (oc / "openclaw.json").write_text("{}", encoding="utf-8")

    report = run_openclaw_rollback(
        openclaw_home=oc,
        dry_run=False,
        restart_gateway=False,
        remove_config=True,
        run_subprocess=_fake_run_ok,
    )
    assert report.ok
    assert not cfg_dir.exists()


def test_run_openclaw_rollback_runtime_only_unwires_twinbox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cfg_dir = tmp_path / ".config" / "twinbox"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "code-root").write_text("/tmp/x\n", encoding="utf-8")
    code_root, state_root, openclaw_home, runtime = _make_runtime_layout(
        tmp_path,
        openclaw_json={
            "skills": {
                "entries": {
                    "twinbox": {"enabled": True, "env": {}},
                    "other": {"enabled": False},
                }
            },
            "gateway": {"token": "keep"},
        },
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TWINBOX_CODE_ROOT", str(code_root.resolve()))
    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))

    report = run_openclaw_rollback(
        code_root=code_root,
        openclaw_home=openclaw_home,
        dry_run=False,
        restart_gateway=False,
        remove_config=False,
        runtime=runtime,
    )

    assert report.ok
    assert [step.id for step in report.steps] == [
        "bridge_remove",
        "strip_openclaw_json",
        "remove_skill_dir",
        "remove_twinbox_config",
        "gateway_restart",
    ]
    written = runtime.file_ops.write_json_calls[0][1]
    assert "twinbox" not in written["skills"]["entries"]
    assert written["skills"]["entries"]["other"]["enabled"] is False
    assert written["gateway"]["token"] == "keep"
    assert runtime.file_ops.remove_tree_calls == [
        openclaw_home / "skills" / "twinbox"
    ]
    assert cfg_dir.exists()


def test_run_openclaw_deploy_ensure_himalaya_skipped_on_non_linux(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code_root, state_root, openclaw_home, runtime = _make_runtime_layout(tmp_path)
    monkeypatch.setenv("TWINBOX_CODE_ROOT", str(code_root.resolve()))
    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    monkeypatch.setattr(
        "twinbox_core.openclaw_deploy_steps.shutil.which",
        lambda _cmd: None,
    )

    report = run_openclaw_deploy(
        code_root=code_root,
        openclaw_home=openclaw_home,
        dry_run=False,
        restart_gateway=False,
        sync_env_from_dotenv=False,
        runtime=runtime,
        skip_bridge=True,
    )

    assert report.ok
    step = next(s for s in report.steps if s.id == "ensure_himalaya")
    assert step.status == "skipped"
    assert step.detail.get("mode") == "skipped"
    assert report.deploy_host_system == "Darwin"
    assert report.deploy_host_machine == "arm64"


def test_run_openclaw_deploy_missing_skill_md_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TWINBOX_CODE_ROOT", raising=False)
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


def test_uninstall_script_success_path_exits_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"--user\" && ( \"$2\" == \"is-active\" || \"$2\" == \"is-enabled\" ) ]]; then\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    systemctl.chmod(0o755)

    openclaw = bin_dir / "openclaw"
    openclaw.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"cron\" && \"$2\" == \"list\" ]]; then\n"
        "  printf '%s\\n' '{\"jobs\": []}'\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$1\" == \"gateway\" && \"$2\" == \"restart\" ]]; then\n"
        "  printf '%s\\n' 'Restarted systemd service: openclaw-gateway.service'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    openclaw.chmod(0o755)

    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "uninstall_openclaw_twinbox.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0


def test_pyproject_declares_runtime_dependencies_for_cli() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"].get("dependencies", [])

    assert any(dep.lower().startswith("pyyaml") for dep in dependencies)


def test_apply_openclaw_plugin_vendor_cwd_sets_plugin_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from twinbox_core.vendor_sync import install_vendor

    state = tmp_path / "st"
    state.mkdir()
    repo = tmp_path / "repo"
    pkg = repo / "src" / "twinbox_core"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("#\n", encoding="utf-8")
    (pkg / "task_cli.py").write_text("#\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    install_vendor(state_root=state, code_root=repo, dry_run=False)

    data: dict[str, Any] = {
        "plugins": {
            "entries": {
                "twinbox-task-tools": {"enabled": True, "config": {"twinboxBin": "/fake/bin"}},
            }
        }
    }
    out = apply_openclaw_plugin_vendor_cwd(data, state)
    vr = (state / "vendor").resolve()
    assert out["plugins"]["entries"]["twinbox-task-tools"]["config"]["cwd"] == str(vr)


def test_apply_openclaw_plugin_vendor_cwd_noop_without_vendor(tmp_path: Path) -> None:
    state = tmp_path / "empty_state"
    state.mkdir()
    data: dict[str, Any] = {"plugins": {"entries": {"twinbox-task-tools": {"config": {}}}}}
    out = apply_openclaw_plugin_vendor_cwd(data, state)
    assert "cwd" not in out["plugins"]["entries"]["twinbox-task-tools"].get("config", {})
