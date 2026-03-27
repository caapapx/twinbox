"""Runtime adapters for OpenClaw deploy orchestration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol


class CommandRunnerPort(Protocol):
    def run(self, argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        """Run a command and capture stdout/stderr."""


class FileOpsPort(Protocol):
    def is_file(self, path: Path) -> bool:
        """Return whether path points to a file."""

    def is_dir(self, path: Path) -> bool:
        """Return whether path points to a directory."""

    def read_text(self, path: Path, *, encoding: str = "utf-8") -> str:
        """Read a text file."""

    def mkdir(self, path: Path, *, parents: bool = True, exist_ok: bool = True) -> None:
        """Create a directory."""

    def write_json_atomic(self, path: Path, data: dict[str, Any]) -> None:
        """Write JSON atomically."""

    def copy_file(self, src: Path, dst: Path) -> None:
        """Copy one file to another location."""

    def remove_tree(self, path: Path) -> None:
        """Remove a directory tree."""


SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]


class LocalFileOps:
    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    def read_text(self, path: Path, *, encoding: str = "utf-8") -> str:
        return path.read_text(encoding=encoding)

    def mkdir(self, path: Path, *, parents: bool = True, exist_ok: bool = True) -> None:
        path.mkdir(parents=parents, exist_ok=exist_ok)

    def write_json_atomic(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        fd, tmp_path = tempfile.mkstemp(
            dir=path.parent, prefix=".openclaw-", suffix=".json.tmp", text=True
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def copy_file(self, src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    def remove_tree(self, path: Path) -> None:
        shutil.rmtree(path)


@dataclass(frozen=True)
class SubprocessCommandRunner:
    runner: SubprocessRunner | None = None

    def run(self, argv: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        runner = self.runner or subprocess.run
        return runner(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
        )


@dataclass(frozen=True)
class OpenClawDeployRuntime:
    file_ops: FileOpsPort
    command_runner: CommandRunnerPort


def build_runtime(
    run_subprocess: SubprocessRunner | None = None,
) -> OpenClawDeployRuntime:
    return OpenClawDeployRuntime(
        file_ops=LocalFileOps(),
        command_runner=SubprocessCommandRunner(run_subprocess),
    )
