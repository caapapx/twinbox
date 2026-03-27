from __future__ import annotations

import json
from pathlib import Path

import pytest

from twinbox_core.loading_pipeline import run_phase1_loading, run_phase4_loading


def _write_mail_env(state_root: Path) -> None:
    (state_root / ".env").write_text(
        "\n".join(
            [
                "MAIL_ADDRESS=owner@example.com",
                "MAIL_ACCOUNT_NAME=myTwinbox",
                "IMAP_HOST=imap.example.com",
                "IMAP_PORT=993",
                "IMAP_ENCRYPTION=tls",
                "IMAP_LOGIN=owner@example.com",
                "IMAP_PASS=secret",
                "SMTP_HOST=smtp.example.com",
                "SMTP_PORT=465",
                "SMTP_ENCRYPTION=tls",
                "SMTP_LOGIN=owner@example.com",
                "SMTP_PASS=secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_phase1_loading_writes_context_and_raw_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_root = tmp_path
    _write_mail_env(state_root)

    recent_date = "2026-03-27T10:00:00+08:00"
    old_date = "2026-02-01T10:00:00+08:00"

    def fake_json_command(
        himalaya_bin: str,
        config_path: Path,
        command: list[str],
        *,
        check: bool = True,
    ) -> object:
        if command == ["folder", "list", "--account", "myTwinbox", "--output", "json"]:
            return [{"name": "INBOX"}]
        if command[:3] == ["envelope", "list", "--account"]:
            page = command[command.index("--page") + 1]
            if page == "1":
                return [
                    {
                        "id": "1",
                        "subject": "Recent thread",
                        "from": {"name": "Alice", "addr": "alice@example.com"},
                        "date": recent_date,
                        "has_attachment": False,
                        "flags": [],
                    },
                    {
                        "id": "2",
                        "subject": "Old thread",
                        "from": {"name": "Bob", "addr": "bob@example.com"},
                        "date": old_date,
                        "has_attachment": True,
                        "flags": ["Seen"],
                    },
                ]
            return []
        if command[:3] == ["message", "read", "--preview"]:
            return "body for 1"
        raise AssertionError(command)

    monkeypatch.setattr("twinbox_core.loading_pipeline.find_himalaya_binary", lambda paths: "/usr/bin/himalaya")
    monkeypatch.setattr("twinbox_core.loading_pipeline._run_himalaya_json", fake_json_command)

    context = run_phase1_loading(state_root, lookback_days=7, sample_body_count=5)

    assert context["stats"]["total_envelopes"] == 1
    assert context["stats"]["sampled_bodies"] == 1
    assert list(context["sampled_bodies"]) == ["1"]

    raw_dir = state_root / "runtime" / "validation" / "phase-1" / "raw"
    assert (raw_dir / "envelopes-merged.json").is_file()
    assert (raw_dir / "sample-bodies.json").is_file()
    assert (state_root / "runtime" / "context" / "phase1-context.json").is_file()

    copied = json.loads((raw_dir / "envelopes-merged.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in copied] == ["1"]


def test_phase4_loading_builds_context_pack_from_phase_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_root = tmp_path
    _write_mail_env(state_root)

    phase1_raw = state_root / "runtime" / "validation" / "phase-1" / "raw"
    phase3_dir = state_root / "runtime" / "validation" / "phase-3"
    phase2_dir = state_root / "runtime" / "validation" / "phase-2"
    runtime_context = state_root / "runtime" / "context"
    phase1_raw.mkdir(parents=True, exist_ok=True)
    phase3_dir.mkdir(parents=True, exist_ok=True)
    phase2_dir.mkdir(parents=True, exist_ok=True)
    runtime_context.mkdir(parents=True, exist_ok=True)

    envelopes = [
        {
            "id": "m1",
            "folder": "INBOX",
            "subject": "项目A",
            "date": "2026-03-27T09:00:00+08:00",
            "from": {"addr": "alice@example.com"},
            "to": {"addr": "owner@example.com"},
        },
        {
            "id": "m2",
            "folder": "INBOX",
            "subject": "Re: 项目A",
            "date": "2026-03-28T09:00:00+08:00",
            "from": {"addr": "bob@example.com"},
            "to": {"addr": "team@example.com"},
        },
        {
            "id": "m3",
            "folder": "INBOX",
            "subject": "项目B",
            "date": "2026-03-28T10:00:00+08:00",
            "from": {"addr": "carol@example.com"},
            "to": {"addr": "owner@example.com"},
        },
    ]
    (phase1_raw / "envelopes-merged.json").write_text(json.dumps(envelopes, ensure_ascii=False), encoding="utf-8")
    (phase1_raw / "sample-bodies.json").write_text(
        json.dumps([{"id": "m2", "folder": "INBOX", "subject": "Re: 项目A", "body": "cached body"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (phase3_dir / "thread-stage-samples.json").write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "thread_key": "项目A(2)",
                        "flow": "IN_FLIGHT",
                        "inferred_stage": "waiting_external",
                        "stage_name": "等待外部反馈",
                        "confidence": 0.9,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (phase3_dir / "lifecycle-model.yaml").write_text("model: ok\n", encoding="utf-8")
    (phase3_dir / "context-pack.json").write_text(
        json.dumps({"top_threads": [{"thread_key": "项目A", "recipient_role": "cc_only"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (phase2_dir / "persona-hypotheses.yaml").write_text('hypothesis: "owner handles approvals"\n', encoding="utf-8")
    (runtime_context / "manual-facts.yaml").write_text("facts:\n  - id: F1\n    value: keep\n", encoding="utf-8")
    (runtime_context / "manual-habits.yaml").write_text("habits: []\n", encoding="utf-8")

    def fake_json_command(
        himalaya_bin: str,
        config_path: Path,
        command: list[str],
        *,
        check: bool = True,
    ) -> object:
        if command[:3] == ["message", "read", "--preview"]:
            return "live body"
        raise AssertionError(command)

    monkeypatch.setattr("twinbox_core.loading_pipeline.find_himalaya_binary", lambda paths: "/usr/bin/himalaya")
    monkeypatch.setattr("twinbox_core.loading_pipeline._run_himalaya_json", fake_json_command)

    context = run_phase4_loading(state_root, lookback_days=7, max_body_fetch=2, max_thread_candidates=10)

    assert context["thread_candidates"] == 2
    assert context["bodies_fetched_live"] == 1
    assert context["human_context"]["has_facts"] is True
    role_map = {thread["thread_key"]: thread["recipient_role"] for thread in context["threads"]}
    assert role_map["项目a"] == "cc_only"
    assert role_map["项目b"] == "direct"
    assert (state_root / "runtime" / "validation" / "phase-4" / "context-pack.json").is_file()
