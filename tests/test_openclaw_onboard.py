"""Tests for the OpenClaw host onboarding wizard."""

from __future__ import annotations

from pathlib import Path

import pytest

from twinbox_core.onboarding import OnboardingState, load_state, save_state
from twinbox_core.openclaw_deploy_types import OpenClawDeployReport
from twinbox_core.openclaw_onboard import run_openclaw_onboard


def _fake_detect_to_env(email: str, *, verbose: bool) -> dict[str, str]:
    del verbose
    return {
        "MAIL_ADDRESS": email,
        "IMAP_HOST": "imap.example.com",
        "IMAP_PORT": "993",
        "IMAP_ENCRYPTION": "ssl",
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": "465",
        "SMTP_ENCRYPTION": "ssl",
    }


def _fake_run_preflight(*, state_root: Path, **_: object) -> tuple[int, dict[str, object]]:
    del state_root
    return 0, {
        "status": "ok",
        "login_stage": "mailbox-connected",
        "missing_env": [],
    }


def test_run_openclaw_onboard_configures_missing_mailbox_and_llm_then_deploys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "SKILL.md").write_text("---\nname: twinbox\n---\n", encoding="utf-8")
    openclaw_home = tmp_path / ".openclaw"
    openclaw_home.mkdir()

    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))
    monkeypatch.setenv("TWINBOX_CODE_ROOT", str(repo))
    monkeypatch.setattr("twinbox_core.openclaw_onboard.shutil.which", lambda _bin: "/usr/bin/openclaw")
    monkeypatch.setattr("twinbox_core.mailbox_detect.detect_to_env", _fake_detect_to_env)
    monkeypatch.setattr("twinbox_core.mailbox.run_preflight", _fake_run_preflight)

    answers = iter(["user@example.com", "openai"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "secret-value")

    deploy_calls: list[dict[str, object]] = []

    def fake_run_openclaw_deploy(**kwargs: object) -> OpenClawDeployReport:
        deploy_calls.append(kwargs)
        return OpenClawDeployReport(ok=True, steps=[])

    report = run_openclaw_onboard(
        code_root=repo,
        openclaw_home=openclaw_home,
        deploy_runner=fake_run_openclaw_deploy,
    )

    assert report.ok is True
    assert report.mailbox["prompted"] is True
    assert report.mailbox["status"] == "ok"
    assert report.llm["prompted"] is True
    assert report.llm["backend"] == "openai"
    assert deploy_calls and deploy_calls[0]["strict"] is True
    assert deploy_calls[0]["sync_env_from_dotenv"] is True

    state = load_state(state_root)
    assert state.current_stage == "profile_setup"
    assert "mailbox_login" in state.completed_stages
    assert "llm_setup" in state.completed_stages


def test_run_openclaw_onboard_skips_prompts_when_mailbox_and_llm_already_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    (state_root / ".env").write_text(
        "\n".join(
            [
                "MAIL_ADDRESS=user@example.com",
                "IMAP_HOST=imap.example.com",
                "IMAP_PORT=993",
                "IMAP_LOGIN=user@example.com",
                "IMAP_PASS=secret-pass",
                "SMTP_HOST=smtp.example.com",
                "SMTP_PORT=465",
                "SMTP_LOGIN=user@example.com",
                "SMTP_PASS=secret-pass",
                "LLM_API_KEY=sk-test",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "SKILL.md").write_text("---\nname: twinbox\n---\n", encoding="utf-8")
    openclaw_home = tmp_path / ".openclaw"
    openclaw_home.mkdir()

    state = OnboardingState(current_stage="material_import", completed_stages=["mailbox_login", "llm_setup", "profile_setup"])
    save_state(state_root, state)

    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))
    monkeypatch.setenv("TWINBOX_CODE_ROOT", str(repo))
    monkeypatch.setattr("twinbox_core.openclaw_onboard.shutil.which", lambda _bin: "/usr/bin/openclaw")
    monkeypatch.setattr("builtins.input", lambda _prompt="": (_ for _ in ()).throw(AssertionError("input should not be called")))
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": (_ for _ in ()).throw(AssertionError("getpass should not be called")))

    def fake_run_openclaw_deploy(**_: object) -> OpenClawDeployReport:
        return OpenClawDeployReport(ok=True, steps=[])

    report = run_openclaw_onboard(
        code_root=repo,
        openclaw_home=openclaw_home,
        deploy_runner=fake_run_openclaw_deploy,
    )

    assert report.ok is True
    assert report.mailbox["prompted"] is False
    assert report.llm["prompted"] is False
    assert report.onboarding["current_stage"] == "material_import"
