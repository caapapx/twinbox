"""Tests for the OpenClaw host onboarding wizard."""

from __future__ import annotations

from pathlib import Path

import pytest

from twinbox_core.onboarding import OnboardingState, load_state, save_state
from twinbox_core.openclaw_deploy_types import OpenClawDeployReport
from twinbox_core.openclaw_onboard import run_openclaw_onboard, run_openclaw_onboard_v2


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


def _write_ready_env(state_root: Path) -> None:
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


class _FakePrompter:
    def __init__(self, *, flow: str = "quickstart", confirm_values: list[bool] | None = None) -> None:
        self.flow = flow
        self.confirm_values = list(confirm_values or [])
        self.events: list[tuple[str, object]] = []

    def intro(self, text: str) -> None:
        self.events.append(("intro", text))

    def outro(self, text: str) -> None:
        self.events.append(("outro", text))

    def note(self, title: str, body: str) -> None:
        self.events.append(("note", {"title": title, "body": body}))

    def select(self, prompt: str, options: list[dict[str, str]], *, default: str | None = None) -> str:
        self.events.append(("select", {"prompt": prompt, "options": options, "default": default}))
        return self.flow

    def confirm(self, prompt: str, *, default: bool = True) -> bool:
        self.events.append(("confirm", {"prompt": prompt, "default": default}))
        if self.confirm_values:
            return self.confirm_values.pop(0)
        return default

    def progress(self, title: str):
        self.events.append(("progress", title))
        prompter = self

        class _Progress:
            def update(self, message: str) -> None:
                prompter.events.append(("progress.update", message))

            def finish(self, message: str) -> None:
                prompter.events.append(("progress.finish", message))

            def fail(self, message: str) -> None:
                prompter.events.append(("progress.fail", message))

        return _Progress()


def test_run_openclaw_onboard_v2_console_prompter_prints_english_shell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    _write_ready_env(state_root)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "SKILL.md").write_text("---\nname: twinbox\n---\n", encoding="utf-8")
    (repo / "openclaw-skill").mkdir()
    (repo / "openclaw-skill" / "openclaw.fragment.json").write_text("{}\n", encoding="utf-8")
    openclaw_home = tmp_path / ".openclaw"
    openclaw_home.mkdir()

    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))
    monkeypatch.setenv("TWINBOX_CODE_ROOT", str(repo))
    monkeypatch.setattr("twinbox_core.openclaw_onboard.shutil.which", lambda _bin: "/usr/bin/openclaw")
    answers = iter([""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    def fake_run_openclaw_onboard(**kwargs: object):
        report = run_openclaw_onboard(
            code_root=repo,
            openclaw_home=openclaw_home,
            fragment_decision=kwargs.get("fragment_decision"),
            input_fn=lambda _prompt="": (_ for _ in ()).throw(AssertionError("input should not be called")),
            secret_input_fn=lambda _prompt="": (_ for _ in ()).throw(AssertionError("secret should not be called")),
            deploy_runner=lambda **deploy_kwargs: OpenClawDeployReport(ok=True, steps=[]),
        )
        report.next_action = "Continue in the twinbox agent with profile setup."
        return report

    _ = run_openclaw_onboard_v2(
        code_root=repo,
        openclaw_home=openclaw_home,
        run_onboard=fake_run_openclaw_onboard,
    )
    out = capsys.readouterr().out

    assert "Twinbox OpenClaw onboarding" in out
    assert "Phase 1 of 2" in out
    assert "1. Quickstart [Recommended]" in out
    assert "2. Advanced" in out
    assert "Running Twinbox host onboarding" in out
    assert "Phase 2 of 2" in out


def test_run_openclaw_onboard_v2_quickstart_defaults_fragment_and_handoffs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    _write_ready_env(state_root)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "SKILL.md").write_text("---\nname: twinbox\n---\n", encoding="utf-8")
    (repo / "openclaw-skill").mkdir()
    (repo / "openclaw-skill" / "openclaw.fragment.json").write_text("{}\n", encoding="utf-8")
    openclaw_home = tmp_path / ".openclaw"
    openclaw_home.mkdir()

    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))
    monkeypatch.setenv("TWINBOX_CODE_ROOT", str(repo))
    monkeypatch.setattr("twinbox_core.openclaw_onboard.shutil.which", lambda _bin: "/usr/bin/openclaw")

    deploy_calls: list[dict[str, object]] = []

    def fake_run_openclaw_onboard(**kwargs: object):
        deploy_calls.append(kwargs)
        report = run_openclaw_onboard(
            code_root=repo,
            openclaw_home=openclaw_home,
            fragment_decision=kwargs.get("fragment_decision"),
            input_fn=lambda _prompt="": (_ for _ in ()).throw(AssertionError("input should not be called")),
            secret_input_fn=lambda _prompt="": (_ for _ in ()).throw(AssertionError("secret should not be called")),
            deploy_runner=lambda **deploy_kwargs: OpenClawDeployReport(ok=True, steps=[]),
        )
        report.next_action = "Continue in the twinbox agent with profile setup."
        return report

    prompter = _FakePrompter(flow="quickstart")
    report = run_openclaw_onboard_v2(
        code_root=repo,
        openclaw_home=openclaw_home,
        run_onboard=fake_run_openclaw_onboard,
        prompter=prompter,
    )

    assert report.ok is True
    assert deploy_calls
    assert deploy_calls[0]["fragment_decision"] is True
    assert ("intro", "Twinbox OpenClaw onboarding") in prompter.events
    assert any(
        event[0] == "note" and event[1]["title"] == "Phase 1 of 2"
        for event in prompter.events
    )
    assert any(
        event[0] == "outro" and "twinbox agent" in str(event[1])
        for event in prompter.events
    )


def test_run_openclaw_onboard_v2_advanced_can_decline_fragment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    _write_ready_env(state_root)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "SKILL.md").write_text("---\nname: twinbox\n---\n", encoding="utf-8")
    (repo / "openclaw-skill").mkdir()
    (repo / "openclaw-skill" / "openclaw.fragment.json").write_text("{}\n", encoding="utf-8")
    openclaw_home = tmp_path / ".openclaw"
    openclaw_home.mkdir()

    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))
    monkeypatch.setenv("TWINBOX_CODE_ROOT", str(repo))
    monkeypatch.setattr("twinbox_core.openclaw_onboard.shutil.which", lambda _bin: "/usr/bin/openclaw")

    onboard_calls: list[dict[str, object]] = []

    def fake_run_openclaw_onboard(**kwargs: object):
        onboard_calls.append(kwargs)
        return run_openclaw_onboard(
            code_root=repo,
            openclaw_home=openclaw_home,
            fragment_decision=kwargs.get("fragment_decision"),
            input_fn=lambda _prompt="": (_ for _ in ()).throw(AssertionError("input should not be called")),
            secret_input_fn=lambda _prompt="": (_ for _ in ()).throw(AssertionError("secret should not be called")),
            deploy_runner=lambda **deploy_kwargs: OpenClawDeployReport(ok=True, steps=[]),
        )

    prompter = _FakePrompter(flow="advanced", confirm_values=[False])
    report = run_openclaw_onboard_v2(
        code_root=repo,
        openclaw_home=openclaw_home,
        run_onboard=fake_run_openclaw_onboard,
        prompter=prompter,
    )

    assert report.ok is True
    assert onboard_calls[0]["fragment_decision"] is False
    assert any(
        event[0] == "note" and event[1]["title"] == "Advanced mode"
        for event in prompter.events
    )
