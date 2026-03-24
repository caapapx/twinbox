"""Tests for mailbox preflight and config rendering."""

from __future__ import annotations

import json
import subprocess

from twinbox_core import mailbox


def _write_minimal_env(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "MAIL_ADDRESS=user@example.com",
                "IMAP_HOST=imap.example.com",
                "IMAP_PORT=993",
                "IMAP_LOGIN=user@example.com",
                "IMAP_PASS=secret",
                "SMTP_HOST=smtp.example.com",
                "SMTP_PORT=465",
                "SMTP_LOGIN=user@example.com",
                "SMTP_PASS=secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return env_file


class TestBuildEffectiveEnv:
    def test_defaults_are_applied_for_account_display_and_encryption(self, tmp_path):
        _write_minimal_env(tmp_path)
        paths = mailbox.resolve_mailbox_paths(state_root=tmp_path)

        effective, defaults_applied, _ = mailbox.build_effective_env(paths, env={})

        assert effective["MAIL_ACCOUNT_NAME"] == "myTwinbox"
        assert effective["MAIL_DISPLAY_NAME"] == "myTwinbox"
        assert effective["IMAP_ENCRYPTION"] == "tls"
        assert effective["SMTP_ENCRYPTION"] == "tls"
        assert defaults_applied["MAIL_ACCOUNT_NAME"] == "myTwinbox"


class TestRunPreflight:
    def test_missing_env_returns_unconfigured_and_fix_commands(self, tmp_path):
        exit_code, result = mailbox.run_preflight(state_root=tmp_path, env={})

        assert exit_code == mailbox.EXIT_CONFIG
        assert result["login_stage"] == "unconfigured"
        assert result["status"] == "fail"
        assert "MAIL_ADDRESS" in result["missing_env"]
        assert result["checks"]["env"]["fix_commands"]

    def test_imap_auth_failure_maps_to_validated_fail(self, tmp_path, monkeypatch):
        _write_minimal_env(tmp_path)

        monkeypatch.setattr(mailbox, "find_himalaya_binary", lambda paths: "/usr/bin/himalaya")

        def fake_run(command, capture_output, text):
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="Authentication failed: invalid credentials",
            )

        monkeypatch.setattr(mailbox.subprocess, "run", fake_run)

        exit_code, result = mailbox.run_preflight(state_root=tmp_path, env={})

        assert exit_code == mailbox.EXIT_IMAP_AUTH
        assert result["login_stage"] == "validated"
        assert result["status"] == "fail"
        assert result["error_code"] == "imap_auth_failed"
        assert result["checks"]["imap"]["status"] == "fail"
        assert (tmp_path / "runtime" / "validation" / "preflight" / "mailbox-smoke.json").exists()

    def test_success_path_is_mailbox_connected_with_warn_status(self, tmp_path, monkeypatch):
        _write_minimal_env(tmp_path)

        monkeypatch.setattr(mailbox, "find_himalaya_binary", lambda paths: "/usr/bin/himalaya")

        def fake_run(command, capture_output, text):
            return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")

        monkeypatch.setattr(mailbox.subprocess, "run", fake_run)

        exit_code, result = mailbox.run_preflight(state_root=tmp_path, env={})

        assert exit_code == mailbox.EXIT_OK
        assert result["login_stage"] == "mailbox-connected"
        assert result["status"] == "warn"
        assert result["checks"]["imap"]["status"] == "success"
        assert result["checks"]["smtp"]["error_code"] == "smtp_skipped_read_only"

        payload = json.loads((tmp_path / "runtime" / "validation" / "preflight" / "mailbox-smoke.json").read_text(encoding="utf-8"))
        assert payload["login_stage"] == "mailbox-connected"
        assert (tmp_path / "runtime" / "validation" / "preflight" / "imap-envelope-sample.json").read_text(encoding="utf-8") == "[]"
