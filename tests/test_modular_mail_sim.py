"""Modular synthetic mail seed (30 envelopes) — no IMAP/LLM."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from twinbox_core.daytime_slice import load_activity_pulse
from twinbox_core.modular_mail_sim import build_simulation_payload, seed_state_root


def test_build_simulation_payload_count_and_intents() -> None:
    data = build_simulation_payload(count=30)
    assert len(data["envelopes"]) == 30
    assert len(data["intent_payload"]["classifications"]) == 30
    assert data["intent_payload"]["stats"]["total_envelopes"] == 30
    assert "collaboration" in data["intent_payload"]["distribution"]


def test_seed_state_root_writes_artifacts_and_pulse(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
    (tmp_path / "runtime").mkdir()

    report = seed_state_root(tmp_path, count=30)

    assert report["envelope_count"] == 30
    p1 = tmp_path / "runtime" / "context" / "phase1-context.json"
    assert p1.is_file()
    ctx = json.loads(p1.read_text(encoding="utf-8"))
    assert len(ctx["envelopes"]) == 30
    assert ctx["stats"]["total_envelopes"] == 30

    ic = json.loads((tmp_path / "runtime" / "validation" / "phase-1" / "intent-classification.json").read_text())
    assert len(ic["classifications"]) == 30

    urgent = yaml.safe_load((tmp_path / "runtime" / "validation" / "phase-4" / "daily-urgent.yaml").read_text())
    assert len(urgent["daily_urgent"]) >= 1

    pulse = load_activity_pulse(tmp_path)
    assert pulse.get("thread_index")
    assert isinstance(pulse["thread_index"], list)
    assert len(pulse["thread_index"]) >= 1


def test_task_cli_reads_seeded_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import subprocess
    import sys

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
    (tmp_path / "runtime").mkdir()
    seed_state_root(tmp_path, count=30)

    env = os.environ.copy()
    env["TWINBOX_STATE_ROOT"] = str(tmp_path)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src") + os.pathsep + env.get("PYTHONPATH", "")

    r = subprocess.run(
        [sys.executable, "-m", "twinbox_core.task_cli", "task", "latest-mail", "--json"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload.get("task") == "latest-mail"
    assert "generated_at" in payload

    r2 = subprocess.run(
        [sys.executable, "-m", "twinbox_core.task_cli", "task", "todo", "--json"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r2.returncode == 0, r2.stderr
    todo = json.loads(r2.stdout)
    assert todo.get("task") == "todo"
    assert "urgent" in todo and "pending" in todo
