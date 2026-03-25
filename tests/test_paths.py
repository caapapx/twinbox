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

    def test_resolve_state_root_uses_new_config_file_before_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            default = root / "default"
            state = root / "state"
            legacy = root / "legacy"
            config_home = root / "config"
            default.mkdir()
            state.mkdir()
            legacy.mkdir()
            (config_home / "twinbox").mkdir(parents=True)
            (config_home / "twinbox" / "state-root").write_text(str(state), encoding="utf-8")
            (config_home / "twinbox" / "canonical-root").write_text(str(legacy), encoding="utf-8")

            resolved = resolve_state_root(
                default,
                env={"XDG_CONFIG_HOME": str(config_home)},
            )

            self.assertEqual(resolved, state.resolve())

    def test_resolve_canonical_root_uses_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code_root = root / "code"
            config_home = root / "config"
            canonical = root / "canonical"
            code_root.mkdir()
            canonical.mkdir()
            (config_home / "twinbox").mkdir(parents=True)
            (config_home / "twinbox" / "canonical-root").write_text(
                str(canonical), encoding="utf-8"
            )

            resolved = resolve_canonical_root(
                code_root,
                env={"XDG_CONFIG_HOME": str(config_home)},
            )

            self.assertEqual(resolved, canonical.resolve())

    def test_resolve_canonical_root_falls_back_to_code_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code_root = Path(tmp)
            config_home = code_root / "config-home"
            config_home.mkdir()

            resolved = resolve_canonical_root(code_root, env={"XDG_CONFIG_HOME": str(config_home)})

            self.assertEqual(resolved, code_root.resolve())

    def test_init_roots_uses_parent_of_script_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code_root = root / "repo"
            config_home = root / "config-home"
            scripts_dir = code_root / "scripts"
            scripts_dir.mkdir(parents=True)
            config_home.mkdir()
            script_path = scripts_dir / "phase4_loading.sh"
            script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            resolved_code_root, resolved_canonical_root = init_roots(
                script_path,
                env={"XDG_CONFIG_HOME": str(config_home)},
            )

            self.assertEqual(resolved_code_root, code_root.resolve())
            self.assertEqual(resolved_canonical_root, code_root.resolve())


if __name__ == "__main__":
    unittest.main()
