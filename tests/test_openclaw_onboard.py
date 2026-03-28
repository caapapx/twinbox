"""Tests for the OpenClaw host onboarding wizard."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest

from twinbox_core.onboarding import OnboardingState, load_state, save_state
from twinbox_core.openclaw_deploy_types import OpenClawDeployReport
from twinbox_core.openclaw_onboard import (
    ConsoleJourneyPrompter,
    run_openclaw_onboard,
    run_openclaw_onboard_v2,
)


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
                "LLM_MODEL=test-model",
                "LLM_API_URL=https://example.com/v1/chat/completions",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_ready_twinbox_config(state_root: Path) -> None:
    (state_root / "twinbox.json").write_text(
        json.dumps(
            {
                "version": 1,
                "mailbox": {
                    "email": "user@example.com",
                    "imap": {
                        "host": "imap.example.com",
                        "port": "993",
                        "login": "user@example.com",
                        "password": "secret-pass",
                    },
                    "smtp": {
                        "host": "smtp.example.com",
                        "port": "465",
                        "login": "user@example.com",
                        "password": "secret-pass",
                    },
                },
                "llm": {
                    "provider": "openai",
                    "model": "test-model",
                    "api_url": "https://example.com/v1/chat/completions",
                    "api_key": "sk-test",
                },
            },
            ensure_ascii=False,
            indent=2,
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

    answers = iter(["user@example.com", "openai", "test-model", "https://example.com/v1/chat/completions"])
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
    assert report.llm["model"] == "test-model"
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
                "LLM_MODEL=test-model",
                "LLM_API_URL=https://example.com/v1/chat/completions",
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
    def __init__(
        self,
        *,
        flow: str = "quickstart",
        select_values: list[str] | None = None,
        confirm_values: list[bool] | None = None,
        text_values: list[str] | None = None,
        secret_values: list[str] | None = None,
    ) -> None:
        self.flow = flow
        self.select_values = list(select_values or [])
        self.confirm_values = list(confirm_values or [])
        self.text_values = list(text_values or [])
        self.secret_values = list(secret_values or [])
        self.events: list[tuple[str, object]] = []

    def intro(self, text: str) -> None:
        self.events.append(("intro", text))

    def outro(self, text: str) -> None:
        self.events.append(("outro", text))

    def cancel(self, summary_title: str, summary_value: str, message: str = "Setup cancelled.") -> None:
        self.events.append(
            ("cancel", {"summary_title": summary_title, "summary_value": summary_value, "message": message})
        )

    def note(self, title: str, body: str, *, complete: bool | None = None) -> None:
        self.events.append(("note", {"title": title, "body": body, "complete": complete}))

    def select(
        self,
        prompt: str,
        options: list[dict[str, str]],
        *,
        default: str | None = None,
        layout: str = "vertical",
    ) -> str:
        self.events.append(
            ("select", {"prompt": prompt, "options": options, "default": default, "layout": layout})
        )
        if self.select_values:
            return self.select_values.pop(0)
        return self.flow

    def confirm(self, prompt: str, *, default: bool = True) -> bool:
        self.events.append(("confirm", {"prompt": prompt, "default": default}))
        if self.confirm_values:
            return self.confirm_values.pop(0)
        return default

    def text(self, prompt: str, *, default: str | None = None) -> str:
        self.events.append(("text", {"prompt": prompt, "default": default}))
        if self.text_values:
            return self.text_values.pop(0)
        return default or ""

    def secret(self, prompt: str, *, allow_empty: bool = False) -> str:
        self.events.append(("secret", {"prompt": prompt, "allow_empty": allow_empty}))
        if self.secret_values:
            return self.secret_values.pop(0)
        return ""

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


class _TTYBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)


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
    monkeypatch.setattr("twinbox_core.mailbox.run_preflight", _fake_run_preflight)
    monkeypatch.setattr(
        "twinbox_core.openclaw_onboard.run_openclaw_deploy",
        lambda **_: OpenClawDeployReport(ok=True, steps=[]),
    )
    answers = iter(["", "", "", "1", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    _ = run_openclaw_onboard_v2(
        code_root=repo,
        openclaw_home=openclaw_home,
    )
    out = capsys.readouterr().out

    assert "TwinBox v1" in out
    assert "TWINBOX" in out
    assert "TwinBox setup" in out
    assert "Security" in out
    assert "Choose onboarding flow" in out
    assert "Mailbox" in out
    assert "LLM" in out
    assert "Phase 2 of 2" in out


def test_console_journey_prompter_select_shows_descriptions_and_reprompts() -> None:
    stream = _TTYBuffer()
    answers = iter(["9", ""])
    prompter = ConsoleJourneyPrompter(stream=stream, input_fn=lambda _prompt="": next(answers))

    choice = prompter.select(
        "Choose onboarding flow",
        options=[
            {"value": "quickstart", "label": "Quickstart", "description": "Use the recommended path with fewer decisions."},
            {"value": "manual", "label": "Manual", "description": "Configure port, network, Tailscale, and auth options."},
        ],
        default="quickstart",
    )

    out = stream.getvalue()
    assert choice == "quickstart"
    assert "Use the recommended path with fewer decisions." in out
    assert "Configure port, network, Tailscale, and auth options." in out
    assert "Enter choice" in out
    assert "Invalid choice" in out


def test_console_journey_prompter_select_supports_arrow_navigation() -> None:
    stream = _TTYBuffer()
    keys = iter(["DOWN", "ENTER"])
    prompter = ConsoleJourneyPrompter(stream=stream, key_reader=lambda: next(keys))

    choice = prompter.select(
        "Choose onboarding flow",
        options=[
            {"value": "quickstart", "label": "Quickstart", "description": "Use the recommended path with fewer decisions."},
            {"value": "manual", "label": "Manual", "description": "Configure port, network, Tailscale, and auth options."},
        ],
        default="quickstart",
    )

    out = stream.getvalue()
    plain = _strip_ansi(out)
    assert choice == "manual"
    assert "Use ↑/↓ to move" in plain
    assert "Press Enter to confirm" in plain
    assert "● Manual (Configure port, network, Tailscale, and auth options.)" in plain
    assert "○ Quickstart" in plain
    assert "[Recommended]" not in plain
    assert "\n  (Configure port, network, Tailscale, and auth options.)" not in plain


def test_console_journey_prompter_select_supports_horizontal_radio_layout() -> None:
    stream = _TTYBuffer()
    keys = iter(["RIGHT", "ENTER"])
    prompter = ConsoleJourneyPrompter(stream=stream, key_reader=lambda: next(keys))

    choice = prompter.select(
        "Continue?",
        options=[
            {"value": "yes", "label": "Yes", "selected_glyph": "●", "unselected_glyph": "○"},
            {"value": "no", "label": "No", "selected_glyph": "●", "unselected_glyph": "○"},
        ],
        default="yes",
        layout="horizontal",
    )

    out = stream.getvalue()
    assert choice == "no"
    assert "Use ←/→ to move" in out
    assert "○ Yes" in out
    assert "● No" in out


def test_console_journey_prompter_vertical_select_clears_previous_taller_frame() -> None:
    """Redraw uses the *previous* frame height so shorter options do not leave orphan lines."""
    stream = _TTYBuffer()
    keys = iter(["DOWN", "UP", "ENTER"])
    prompter = ConsoleJourneyPrompter(stream=stream, key_reader=lambda: next(keys), width=36)

    choice = prompter.select(
        "Step",
        [
            {
                "value": "tall",
                "label": "Option A very long label",
                "description": "Long description that wraps on a narrow terminal width.",
            },
            {"value": "short", "label": "B", "description": "x"},
        ],
        default="tall",
    )
    assert choice == "tall"


def test_console_journey_prompter_enter_clears_menu_before_next_select() -> None:
    stream = _TTYBuffer()
    keys = iter(["ENTER", "ENTER"])
    prompter = ConsoleJourneyPrompter(stream=stream, key_reader=lambda: next(keys), width=48)
    assert prompter.select("Menu one", [{"value": "a", "label": "A", "description": "z" * 80}], default="a") == "a"
    assert prompter.select("Menu two", [{"value": "b", "label": "B"}], default="b") == "b"
    plain = _strip_ansi(stream.getvalue())
    assert plain.count("Menu two") == 1


def test_console_journey_prompter_note_draws_closed_box_with_rail_glyphs() -> None:
    stream = io.StringIO()
    prompter = ConsoleJourneyPrompter(stream=stream, width=64)

    prompter.note("Security", "First line.\n\nSecond paragraph.", complete=False)
    out = stream.getvalue()
    assert "┌" in out and "┐" in out and "└" in out and "┘" in out
    assert "◆" in out
    assert "Security" in out
    assert "First line." in out

    stream2 = io.StringIO()
    prompter2 = ConsoleJourneyPrompter(stream=stream2, width=64)
    prompter2.note("Mailbox", "Configured.", complete=True)
    assert "◇" in stream2.getvalue()

    stream3 = io.StringIO()
    prompter3 = ConsoleJourneyPrompter(stream=stream3, width=64)
    prompter3.note("Intro", "No rail glyph.", complete=None)
    out3 = stream3.getvalue()
    assert "┌" in out3
    assert "◆" not in out3 and "◇" not in out3
    assert "Intro" in out3


def test_console_journey_prompter_ctrl_c_in_select_raises_keyboard_interrupt() -> None:
    stream = _TTYBuffer()
    keys = iter(["\x03"])
    prompter = ConsoleJourneyPrompter(stream=stream, key_reader=lambda: next(keys))

    with pytest.raises(KeyboardInterrupt):
        prompter.select(
            "Choose onboarding flow",
            options=[
                {"value": "quickstart", "label": "Quickstart", "description": "Use the recommended path with fewer decisions."},
                {"value": "manual", "label": "Manual", "description": "Configure port, network, Tailscale, and auth options."},
            ],
            default="quickstart",
        )


def test_console_journey_prompter_cancel_prints_compact_footer() -> None:
    stream = _TTYBuffer()
    prompter = ConsoleJourneyPrompter(stream=stream)

    prompter.cancel("Setup mode", "Manual")

    plain = _strip_ansi(stream.getvalue())
    assert "■  Setup mode" in plain
    assert "│  Manual" in plain
    assert "└  Setup cancelled." in plain


def test_console_journey_prompter_note_wraps_to_terminal_width() -> None:
    stream = _TTYBuffer()
    prompter = ConsoleJourneyPrompter(stream=stream, width=48)

    prompter.note(
        "TwinBox setup",
        "This wizard verifies host wiring first, then hands you off to the twinbox agent for profile, materials, rules, and notifications.",
    )

    plain = _strip_ansi(stream.getvalue())
    lines = [line for line in plain.splitlines() if line]
    assert max(len(line) for line in lines) <= 50
    assert "hands you off" in plain
    assert "twinbox agent" in plain
    assert "TwinBox setup" in plain
    assert plain.count("│") >= 2


def test_console_journey_prompter_select_clears_lines_before_rerender() -> None:
    stream = _TTYBuffer()
    keys = iter(["DOWN", "ENTER"])
    prompter = ConsoleJourneyPrompter(stream=stream, key_reader=lambda: next(keys), width=48)

    _ = prompter.select(
        "Choose onboarding flow",
        options=[
            {"value": "quickstart", "label": "Quickstart", "description": "Use the recommended path with fewer decisions."},
            {"value": "manual", "label": "Manual", "description": "Configure port, network, Tailscale, and auth options."},
        ],
        default="quickstart",
    )

    out = stream.getvalue()
    assert "\033[2K" in out
    assert "\033[" in out


def test_console_journey_prompter_progress_renders_tty_spinner_frames() -> None:
    stream = _TTYBuffer()
    prompter = ConsoleJourneyPrompter(stream=stream)

    progress = prompter.progress("Running Twinbox host onboarding")
    progress.update("Checking mailbox, LLM, and OpenClaw wiring prerequisites")
    progress.finish("Host wiring verified and onboarding handoff prepared")

    out = stream.getvalue()
    assert "⠋" in out or "⠙" in out or "⠹" in out
    assert "\r" in out
    assert "OK: Host wiring verified and onboarding handoff prepared" in out


def test_run_openclaw_onboard_v2_requires_explicit_steps_even_with_existing_values(
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
    monkeypatch.setattr("twinbox_core.mailbox.run_preflight", _fake_run_preflight)

    def fail_if_old_onboard_is_used(**_: object):
        raise AssertionError("run_openclaw_onboard should not be used by V2 anymore")

    monkeypatch.setattr(
        "twinbox_core.openclaw_onboard.run_openclaw_deploy",
        lambda **_: OpenClawDeployReport(ok=True, steps=[]),
    )

    prompter = _FakePrompter(
        select_values=[
            "continue",
            "quickstart",
            "use_existing",
            "use_existing",
            "yes",
            "apply",
        ],
    )
    report = run_openclaw_onboard_v2(
        code_root=repo,
        openclaw_home=openclaw_home,
        run_onboard=fail_if_old_onboard_is_used,
        prompter=prompter,
    )

    assert report.ok is True
    note_titles = [event[1]["title"] for event in prompter.events if event[0] == "note"]
    assert note_titles.count("Existing config detected") == 2
    assert all(
        title in note_titles
        for title in ["TwinBox setup", "Security", "Mailbox", "LLM", "Twinbox tools integration", "Apply setup"]
    )
    config_handling_selects = [
        event[1] for event in prompter.events if event[0] == "select" and event[1]["prompt"] == "◆  Config handling"
    ]
    assert len(config_handling_selects) == 2
    assert [option["label"] for option in config_handling_selects[0]["options"]] == [
        "Use existing values",
        "Update values",
        "Reset",
    ]
    assert not any(event[0] == "select" and event[1]["prompt"] == "Choose LLM setup" for event in prompter.events)
    apply_note = next(
        event[1] for event in prompter.events if event[0] == "note" and event[1]["title"] == "Apply setup"
    )
    assert "LLM: test-model" in apply_note["body"]
    assert any(event[0] == "note" and event[1]["title"] == "Apply setup" for event in prompter.events)
    assert any(event[0] == "outro" and "twinbox agent" in str(event[1]) for event in prompter.events)


def test_run_openclaw_onboard_v2_reads_existing_values_from_twinbox_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    _write_ready_twinbox_config(state_root)
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
    monkeypatch.setattr("twinbox_core.mailbox.run_preflight", _fake_run_preflight)
    monkeypatch.setattr(
        "twinbox_core.openclaw_onboard.run_openclaw_deploy",
        lambda **_: OpenClawDeployReport(ok=True, steps=[]),
    )

    prompter = _FakePrompter(
        select_values=[
            "continue",
            "quickstart",
            "use_existing",
            "use_existing",
            "yes",
            "apply",
        ],
    )
    report = run_openclaw_onboard_v2(
        code_root=repo,
        openclaw_home=openclaw_home,
        prompter=prompter,
    )

    assert report.ok is True
    apply_note = next(
        event[1] for event in prompter.events if event[0] == "note" and event[1]["title"] == "Apply setup"
    )
    assert "Mailbox: user@example.com" in apply_note["body"]
    assert "LLM: test-model" in apply_note["body"]


def test_run_openclaw_onboard_v2_collects_llm_inputs_before_validation_progress(
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
    monkeypatch.setattr("twinbox_core.mailbox.run_preflight", _fake_run_preflight)
    monkeypatch.setattr(
        "twinbox_core.openclaw_onboard.run_openclaw_deploy",
        lambda **_: OpenClawDeployReport(ok=True, steps=[]),
    )

    prompter = _FakePrompter(
        select_values=[
            "continue",
            "quickstart",
            "use_existing",
            "update",
            "openai",
            "yes",
            "apply",
        ],
        secret_values=[""],
        text_values=["https://example.com/v1/chat/completions", "test-model"],
    )

    report = run_openclaw_onboard_v2(
        code_root=repo,
        openclaw_home=openclaw_home,
        prompter=prompter,
    )

    assert report.ok is True
    api_url_index = next(
        index
        for index, event in enumerate(prompter.events)
        if event[0] == "text" and event[1]["prompt"] == "API URL"
    )
    api_key_index = next(
        index
        for index, event in enumerate(prompter.events)
        if event[0] == "secret" and event[1]["prompt"] == "API key"
    )
    model_index = next(
        index
        for index, event in enumerate(prompter.events)
        if event[0] == "text" and event[1]["prompt"] == "Model ID"
    )
    progress_index = next(
        index
        for index, event in enumerate(prompter.events)
        if event[0] == "progress" and event[1] == "Validating LLM configuration"
    )
    assert api_url_index < api_key_index
    assert api_key_index < progress_index
    assert model_index < progress_index


def test_run_openclaw_onboard_v2_collects_mailbox_inputs_before_validation_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
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
    monkeypatch.setattr("twinbox_core.mailbox_detect.detect_to_env", _fake_detect_to_env)
    monkeypatch.setattr("twinbox_core.mailbox.run_preflight", _fake_run_preflight)
    monkeypatch.setattr(
        "twinbox_core.openclaw_onboard.run_openclaw_deploy",
        lambda **_: OpenClawDeployReport(ok=True, steps=[]),
    )

    prompter = _FakePrompter(
        select_values=[
            "continue",
            "quickstart",
            "auto",
            "openai",
            "yes",
            "apply",
        ],
        text_values=[
            "user@example.com",
            "test-model",
            "https://example.com/v1/chat/completions",
        ],
        secret_values=["mail-secret", "llm-secret"],
    )

    report = run_openclaw_onboard_v2(
        code_root=repo,
        openclaw_home=openclaw_home,
        prompter=prompter,
    )

    assert report.ok is True
    mailbox_text_index = next(index for index, event in enumerate(prompter.events) if event[0] == "text")
    mailbox_secret_index = next(index for index, event in enumerate(prompter.events) if event[0] == "secret")
    mailbox_progress_index = next(
        index
        for index, event in enumerate(prompter.events)
        if event[0] == "progress" and event[1] == "Checking mailbox settings"
    )
    assert mailbox_text_index < mailbox_progress_index
    assert mailbox_secret_index < mailbox_progress_index


def test_run_openclaw_onboard_v2_times_out_llm_validation(
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
    monkeypatch.setattr("twinbox_core.mailbox.run_preflight", _fake_run_preflight)
    monkeypatch.setattr(
        "twinbox_core.openclaw_onboard.run_openclaw_deploy",
        lambda **_: OpenClawDeployReport(ok=True, steps=[]),
    )

    def slow_llm_update_runner(**kwargs):
        import time

        time.sleep(0.05)
        return True, {
            "prompted": True,
            "configured": True,
            "backend": "openai",
            "model": "test-model",
            "url": "https://example.com/v1/chat/completions",
        }, kwargs["dotenv"]

    prompter = _FakePrompter(
        select_values=[
            "continue",
            "quickstart",
            "use_current_mailbox",
            "openai",
        ],
        secret_values=["new-key"],
        text_values=["test-model", "https://example.com/v1/chat/completions"],
    )

    report = run_openclaw_onboard_v2(
        code_root=repo,
        openclaw_home=openclaw_home,
        prompter=prompter,
        llm_update_runner=slow_llm_update_runner,
        llm_validation_timeout_seconds=0.01,
    )

    assert report.ok is False
    assert "timed out" in report.error.lower()
    assert ("progress.fail", "LLM validation timed out") in prompter.events


def test_run_openclaw_onboard_v2_times_out_mailbox_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
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
    monkeypatch.setattr("twinbox_core.mailbox_detect.detect_to_env", _fake_detect_to_env)

    def slow_mailbox_apply_runner(**kwargs):
        import time

        time.sleep(0.05)
        return True, {
            "prompted": True,
            "configured": True,
            "missing_required": [],
            "status": "ok",
            "login_stage": "mailbox-connected",
            "mail_address": kwargs["updates"]["MAIL_ADDRESS"],
            "env_file_path": str(kwargs["env_file"]),
        }, kwargs["dotenv"] | kwargs["updates"]

    prompter = _FakePrompter(
        select_values=[
            "continue",
            "quickstart",
            "auto",
        ],
        text_values=["user@example.com"],
        secret_values=["mail-secret"],
    )

    report = run_openclaw_onboard_v2(
        code_root=repo,
        openclaw_home=openclaw_home,
        prompter=prompter,
        mailbox_apply_runner=slow_mailbox_apply_runner,
        mailbox_validation_timeout_seconds=0.01,
    )

    assert report.ok is False
    assert "timed out" in report.error.lower()
    assert ("progress.fail", "Mailbox validation timed out") in prompter.events


def test_run_openclaw_onboard_v2_allows_llm_skip_and_returns_incomplete_handoff(
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
            ]
        )
        + "\n",
        encoding="utf-8",
    )
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
    monkeypatch.setattr("twinbox_core.mailbox.run_preflight", _fake_run_preflight)
    monkeypatch.setattr(
        "twinbox_core.openclaw_onboard.run_openclaw_deploy",
        lambda **_: OpenClawDeployReport(ok=True, steps=[]),
    )

    prompter = _FakePrompter(
        select_values=[
            "continue",
            "quickstart",
            "use_existing",
            "skip",
            "yes",
            "apply",
        ]
    )
    report = run_openclaw_onboard_v2(
        code_root=repo,
        openclaw_home=openclaw_home,
        run_onboard=lambda **_: (_ for _ in ()).throw(AssertionError("old onboard should not be used")),
        prompter=prompter,
    )

    assert report.ok is False
    llm_select = next(
        event[1] for event in prompter.events if event[0] == "select" and event[1]["prompt"] == "Choose LLM setup"
    )
    assert [option["label"] for option in llm_select["options"]] == [
        "Configure OpenAI",
        "Configure Anthropic",
        "Skip for now",
    ]
    assert report.onboarding["current_stage"] == "llm_setup"
    assert "llm" in report.error.lower()
    assert "next guided conversation stage is llm_setup" in report.next_action.lower()


def test_run_openclaw_onboard_v2_hides_use_current_llm_when_only_api_key_exists(
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
    (repo / "openclaw-skill").mkdir()
    (repo / "openclaw-skill" / "openclaw.fragment.json").write_text("{}\n", encoding="utf-8")
    openclaw_home = tmp_path / ".openclaw"
    openclaw_home.mkdir()

    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))
    monkeypatch.setenv("TWINBOX_CODE_ROOT", str(repo))
    monkeypatch.setattr("twinbox_core.openclaw_onboard.shutil.which", lambda _bin: "/usr/bin/openclaw")
    monkeypatch.setattr("twinbox_core.mailbox.run_preflight", _fake_run_preflight)
    monkeypatch.setattr(
        "twinbox_core.openclaw_onboard.run_openclaw_deploy",
        lambda **_: OpenClawDeployReport(ok=True, steps=[]),
    )

    prompter = _FakePrompter(
        select_values=[
            "continue",
            "quickstart",
            "use_existing",
            "skip",
            "yes",
            "apply",
        ]
    )
    report = run_openclaw_onboard_v2(
        code_root=repo,
        openclaw_home=openclaw_home,
        prompter=prompter,
    )

    llm_select = next(
        event[1] for event in prompter.events if event[0] == "select" and event[1]["prompt"] == "Choose LLM setup"
    )
    assert [option["label"] for option in llm_select["options"]] == [
        "Configure OpenAI",
        "Configure Anthropic",
        "Skip for now",
    ]
    assert report.ok is False


def test_run_openclaw_onboard_v2_ctrl_c_returns_cancelled_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    _write_ready_env(state_root)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "SKILL.md").write_text("---\nname: twinbox\n---\n", encoding="utf-8")
    openclaw_home = tmp_path / ".openclaw"
    openclaw_home.mkdir()

    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(state_root))
    monkeypatch.setenv("TWINBOX_CODE_ROOT", str(repo))
    monkeypatch.setattr("twinbox_core.openclaw_onboard.shutil.which", lambda _bin: "/usr/bin/openclaw")

    class _CtrlCPrompter(_FakePrompter):
        def select(self, *args, **kwargs):
            raise KeyboardInterrupt

    prompter = _CtrlCPrompter()
    report = run_openclaw_onboard_v2(
        code_root=repo,
        openclaw_home=openclaw_home,
        prompter=prompter,
    )

    assert report.ok is False
    assert report.error == "Setup cancelled."
    assert any(event[0] == "cancel" for event in prompter.events)
