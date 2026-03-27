from __future__ import annotations

import argparse
from pathlib import Path

from twinbox_core import task_cli_loading


def _parse_loading_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    task_cli_loading.register_loading_parser(subparsers)
    return parser.parse_args(["loading", *argv])


def test_dispatch_loading_phase1_delegates_to_loading_pipeline(monkeypatch) -> None:
    seen: dict[str, object] = {}
    expected_state_root = Path.cwd().resolve()

    def fake_main(argv: list[str] | None = None) -> int:
        seen["argv"] = list(argv or [])
        return 0

    import twinbox_core.loading_pipeline as loading_pipeline

    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(expected_state_root))
    monkeypatch.setattr(loading_pipeline, "main", fake_main)

    args = _parse_loading_args(["phase1", "--", "--lookback-days", "3"])
    exit_code = task_cli_loading.dispatch_loading(args)

    assert exit_code == 0
    assert seen["argv"][0:3] == ["phase1", "--state-root", str(expected_state_root)]
    assert seen["argv"][3:] == ["--lookback-days", "3"]


def test_dispatch_loading_phase2_uses_python_context_builder(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run_phase2_loading(state_root: Path) -> dict[str, object]:
        seen["state_root"] = state_root
        return {}

    import twinbox_core.context_builder as context_builder

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
    monkeypatch.setattr(context_builder, "run_phase2_loading", fake_run_phase2_loading)

    args = _parse_loading_args(["phase2"])
    exit_code = task_cli_loading.dispatch_loading(args)

    assert exit_code == 0
    assert seen["state_root"] == tmp_path.resolve()
