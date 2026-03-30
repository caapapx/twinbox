from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from twinbox_core.paths import (
    PathResolutionError,
    canonical_root_file,
    code_root_file,
    init_roots,
    resolve_canonical_root,
    resolve_code_root,
    resolve_daemon_state_root,
    resolve_existing_dir,
    resolve_state_root,
    state_root_file,
)


class PathsTest(unittest.TestCase):
    def test_resolve_existing_dir_returns_real_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "actual"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)

            resolved = resolve_existing_dir(link)

            self.assertEqual(resolved, target.resolve())

    def test_canonical_root_file_prefers_override(self) -> None:
        env = {"TWINBOX_CANONICAL_ROOT_FILE": "/tmp/custom-root"}

        self.assertEqual(canonical_root_file(env), Path("/tmp/custom-root"))

    def test_code_root_file_prefers_override(self) -> None:
        env = {"TWINBOX_CODE_ROOT_FILE": "/tmp/custom-code-root"}

        self.assertEqual(code_root_file(env), Path("/tmp/custom-code-root"))

    def test_state_root_file_prefers_override(self) -> None:
        env = {"TWINBOX_STATE_ROOT_FILE": "/tmp/custom-state-root"}

        self.assertEqual(state_root_file(env), Path("/tmp/custom-state-root"))

    def test_resolve_canonical_root_prefers_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code_root = root / "code"
            canonical = root / "canonical"
            code_root.mkdir()
            canonical.mkdir()

            resolved = resolve_canonical_root(
                code_root,
                env={"TWINBOX_CANONICAL_ROOT": str(canonical)},
            )

            self.assertEqual(resolved, canonical.resolve())

    def test_resolve_code_root_prefers_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code_root = root / "code"
            configured = root / "configured-code"
            code_root.mkdir()
            configured.mkdir()

            resolved = resolve_code_root(
                code_root,
                env={"TWINBOX_CODE_ROOT": str(configured)},
            )

            self.assertEqual(resolved, configured.resolve())

    def test_resolve_code_root_ascends_from_nested_repo_dir(self) -> None:
        """CWD under cmd/twinbox-go must not become the code root (fragment path)."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            repo = home / "twinbox"
            (repo / "integrations" / "openclaw").mkdir(parents=True)
            (repo / "src" / "twinbox_core").mkdir(parents=True)
            go_dir = repo / "cmd" / "twinbox-go"
            go_dir.mkdir(parents=True)

            resolved = resolve_code_root(
                go_dir,
                env={"HOME": str(home)},
            )

            self.assertEqual(resolved, repo.resolve())

    def test_resolve_state_root_prefers_new_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default = root / "default"
            configured = root / "state"
            default.mkdir()
            configured.mkdir()

            resolved = resolve_state_root(
                default,
                env={"TWINBOX_STATE_ROOT": str(configured)},
            )

            self.assertEqual(resolved, configured.resolve())

    def test_resolve_state_root_falls_back_to_legacy_config_file(self) -> None:
        """If ~/.twinbox/state-root is absent, still honor ~/.config/twinbox/state-root."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            default = home / "default"
            state = home / "state"
            config_home = home / ".config"
            default.mkdir()
            state.mkdir()
            (config_home / "twinbox").mkdir(parents=True)
            (config_home / "twinbox" / "state-root").write_text(str(state), encoding="utf-8")

            resolved = resolve_state_root(
                default,
                env={"HOME": str(home), "XDG_CONFIG_HOME": str(config_home)},
            )

            self.assertEqual(resolved, state.resolve())

    def test_resolve_state_root_uses_new_config_file_before_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            default = home / "default"
            state = home / "state"
            legacy = home / "legacy"
            config_home = home / ".config"
            default.mkdir()
            state.mkdir()
            legacy.mkdir()
            (home / ".twinbox").mkdir(parents=True)
            (home / ".twinbox" / "state-root").write_text(str(state), encoding="utf-8")
            (config_home / "twinbox").mkdir(parents=True)
            (config_home / "twinbox" / "state-root").write_text("bogus", encoding="utf-8")
            (config_home / "twinbox" / "canonical-root").write_text(str(legacy), encoding="utf-8")

            resolved = resolve_state_root(
                default,
                env={"HOME": str(home), "XDG_CONFIG_HOME": str(config_home)},
            )

            self.assertEqual(resolved, state.resolve())

    def test_resolve_daemon_state_root_explicit_env_no_exist(self) -> None:
        """Explicit TWINBOX_STATE_ROOT is not strict; daemon validates is_dir()."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default = root / "default"
            default.mkdir()
            ghost = root / "nope"
            resolved = resolve_daemon_state_root(
                default,
                env={"TWINBOX_STATE_ROOT": str(ghost)},
            )
            self.assertEqual(resolved, ghost.resolve())
            self.assertFalse(resolved.is_dir())

    def test_resolve_daemon_state_root_falls_back_like_resolve_state_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            default = home / "default"
            state = home / "state"
            config_home = home / ".config"
            default.mkdir()
            state.mkdir()
            (home / ".twinbox").mkdir(parents=True)
            (home / ".twinbox" / "state-root").write_text(str(state), encoding="utf-8")
            env = {"HOME": str(home), "XDG_CONFIG_HOME": str(config_home)}

            r1 = resolve_state_root(default, env=env)
            r2 = resolve_daemon_state_root(default, env=env)

            self.assertEqual(r1, r2)
            self.assertEqual(r2, state.resolve())

    def test_resolve_canonical_root_uses_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            code_root = home / "code"
            config_home = home / ".config"
            canonical = home / "canonical"
            code_root.mkdir()
            canonical.mkdir()
            (home / ".twinbox").mkdir(parents=True)
            (home / ".twinbox" / "canonical-root").write_text(str(canonical), encoding="utf-8")

            resolved = resolve_canonical_root(
                code_root,
                env={"HOME": str(home), "XDG_CONFIG_HOME": str(config_home)},
            )

            self.assertEqual(resolved, canonical.resolve())

    def test_resolve_canonical_root_falls_back_to_code_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            home.mkdir()
            code_root = home / "cr"
            code_root.mkdir()

            resolved = resolve_canonical_root(code_root, env={"HOME": str(home)})

            self.assertEqual(resolved, code_root.resolve())

    def test_init_roots_uses_parent_of_script_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            code_root = home / "repo"
            scripts_dir = code_root / "scripts"
            scripts_dir.mkdir(parents=True)
            pkg = code_root / "src" / "twinbox_core"
            pkg.mkdir(parents=True)
            marker = pkg / "__init__.py"
            marker.write_text("# marker\n", encoding="utf-8")
            script_path = scripts_dir / "twinbox_paths.sh"
            script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            resolved_code_root, resolved_canonical_root = init_roots(
                script_path,
                env={"HOME": str(home)},
            )

            self.assertEqual(resolved_code_root, code_root.resolve())
            self.assertEqual(resolved_canonical_root, code_root.resolve())


if __name__ == "__main__":
    unittest.main()
