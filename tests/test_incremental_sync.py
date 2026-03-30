"""Tests for twinbox_core.incremental_sync (daytime incremental Phase 1)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from twinbox_core.imap_incremental import EXIT_FALLBACK


@pytest.fixture
def state_layout(tmp_path: Path) -> Path:
    root = tmp_path / "state"
    root.mkdir()
    (root / ".env").write_text(
        "\n".join(
            [
                "MAIL_ADDRESS=user@example.com",
                "MAIL_ACCOUNT_NAME=myTwinbox",
                "MAIL_DISPLAY_NAME=User",
                "IMAP_HOST=imap.example.com",
                "IMAP_PORT=993",
                "IMAP_LOGIN=user@example.com",
                "IMAP_PASS=secret",
                "IMAP_ENCRYPTION=tls",
                "SMTP_HOST=smtp.example.com",
                "SMTP_PORT=465",
                "SMTP_LOGIN=user@example.com",
                "SMTP_PASS=secret",
                "SMTP_ENCRYPTION=tls",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "runtime" / "himalaya").mkdir(parents=True)
    return root


def test_incremental_sync_fallback_runs_loading_pipeline(
    state_layout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from twinbox_core import incremental_sync as inc

    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        if "-m" in argv and argv[argv.index("-m") + 1] == "twinbox_core.imap_incremental":
            return SimpleNamespace(returncode=EXIT_FALLBACK, stderr="")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(inc.subprocess, "run", fake_run)

    rc = inc.run_incremental_sync(state_layout, sample_body_count=5, lookback_days=3)
    assert rc == 0
    assert len(calls) >= 2
    assert any("twinbox_core.imap_incremental" in c for c in calls)
    assert any("twinbox_core.loading_pipeline" in c and "phase1" in c for c in calls)
