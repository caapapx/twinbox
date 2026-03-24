from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from twinbox_core.paths import (
    PathResolutionError,
    canonical_root_file,
    init_roots,
    resolve_canonical_root,
    resolve_existing_dir,
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

            resolved = resolve_canonical_root(code_root, env={})

            self.assertEqual(resolved, code_root.resolve())

    def test_init_roots_uses_parent_of_script_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code_root = root / "repo"
            scripts_dir = code_root / "scripts"
            scripts_dir.mkdir(parents=True)
            script_path = scripts_dir / "phase4_loading.sh"
            script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

            resolved_code_root, resolved_canonical_root = init_roots(script_path, env={})

            self.assertEqual(resolved_code_root, code_root.resolve())
            self.assertEqual(resolved_canonical_root, code_root.resolve())


if __name__ == "__main__":
    unittest.main()
