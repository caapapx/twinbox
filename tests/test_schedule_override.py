from __future__ import annotations

import json

import yaml

from twinbox_core import schedule_override


def test_load_schedule_config_merges_skill_defaults_with_runtime_overrides(tmp_path):
    override_path = tmp_path / "runtime" / "context" / "schedule-overrides.yaml"
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(
        yaml.safe_dump(
            {
                "timezone": "Asia/Shanghai",
                "overrides": {
                    "daily-refresh": "30 9 * * *",
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    config = schedule_override.load_schedule_config(state_root=tmp_path)

    by_name = {row["name"]: row for row in config["schedules"]}
    assert config["timezone"] == "Asia/Shanghai"
    assert by_name["daily-refresh"]["default_cron"] == "30 8 * * *"
    assert by_name["daily-refresh"]["effective_cron"] == "30 9 * * *"
    assert by_name["daily-refresh"]["source"] == "override"
    assert by_name["nightly-full-refresh"]["source"] == "default"


def test_update_schedule_override_persists_yaml_with_default_timezone(tmp_path):
    result = schedule_override.update_schedule_override(
        state_root=tmp_path,
        job_name="weekly-refresh",
        cron="15 18 * * 5",
    )

    payload = yaml.safe_load((tmp_path / "runtime" / "context" / "schedule-overrides.yaml").read_text(encoding="utf-8"))
    assert result["timezone"] == "Asia/Shanghai"
    assert payload["timezone"] == "Asia/Shanghai"
    assert payload["overrides"]["weekly-refresh"] == "15 18 * * 5"


def test_reset_schedule_override_removes_job_but_keeps_other_overrides(tmp_path):
    schedule_override.update_schedule_override(
        state_root=tmp_path,
        job_name="daily-refresh",
        cron="30 9 * * *",
    )
    schedule_override.update_schedule_override(
        state_root=tmp_path,
        job_name="weekly-refresh",
        cron="15 18 * * 5",
    )

    result = schedule_override.reset_schedule_override(
        state_root=tmp_path,
        job_name="daily-refresh",
    )

    payload = yaml.safe_load((tmp_path / "runtime" / "context" / "schedule-overrides.yaml").read_text(encoding="utf-8"))
    assert result["reset"] is True
    assert "daily-refresh" not in payload["overrides"]
    assert payload["overrides"]["weekly-refresh"] == "15 18 * * 5"


def test_validate_cron_rejects_non_five_field_expression():
    message = schedule_override.validate_cron_expression("30 9 * *")

    assert message is not None
    assert "5 fields" in message


def test_sync_openclaw_schedule_updates_existing_matching_job():
    calls: list[list[str]] = []

    def fake_runner(argv: list[str]) -> str:
        calls.append(argv)
        if argv[:4] == ["openclaw", "cron", "list", "--all"]:
            return json.dumps(
                {
                    "jobs": [
                        {
                            "id": "job-1",
                            "name": "some-existing-name",
                            "payload": {
                                "kind": "systemEvent",
                                "text": '{"kind":"twinbox.schedule","job":"daytime-sync"}',
                            },
                        }
                    ]
                },
                ensure_ascii=False,
            )
        if argv[:4] == ["openclaw", "cron", "edit", "job-1"]:
            return ""
        raise AssertionError(f"Unexpected argv: {argv}")

    result = schedule_override.sync_schedule_to_openclaw(
        job_name="daily-refresh",
        cron="45 9 * * *",
        timezone="Asia/Shanghai",
        runner=fake_runner,
    )

    assert result["status"] == "updated"
    assert result["job_id"] == "job-1"
    assert calls[1][:4] == ["openclaw", "cron", "edit", "job-1"]
    assert "--cron" in calls[1]
    assert "45 9 * * *" in calls[1]
    assert "--tz" in calls[1]
    assert "Asia/Shanghai" in calls[1]
    assert "--system-event" in calls[1]
    assert '{"kind":"twinbox.schedule","job":"daytime-sync","event_source":"openclaw.system-event"}' in calls[1]


def test_sync_openclaw_schedule_creates_missing_job():
    calls: list[list[str]] = []

    def fake_runner(argv: list[str]) -> str:
        calls.append(argv)
        if argv[:4] == ["openclaw", "cron", "list", "--all"]:
            return json.dumps({"jobs": []}, ensure_ascii=False)
        if argv[:3] == ["openclaw", "cron", "add"]:
            return json.dumps({"job": {"id": "job-9"}}, ensure_ascii=False)
        raise AssertionError(f"Unexpected argv: {argv}")

    result = schedule_override.sync_schedule_to_openclaw(
        job_name="weekly-refresh",
        cron="15 18 * * 5",
        timezone="Asia/Shanghai",
        runner=fake_runner,
    )

    assert result["status"] == "created"
    assert result["job_id"] == "job-9"
    assert calls[1][:3] == ["openclaw", "cron", "add"]
    assert "--name" in calls[1]
    assert "twinbox-weekly-refresh" in calls[1]
    assert "--cron" in calls[1]
    assert "15 18 * * 5" in calls[1]


def test_sync_openclaw_schedule_rejects_duplicate_matching_jobs():
    def fake_runner(argv: list[str]) -> str:
        if argv[:4] == ["openclaw", "cron", "list", "--all"]:
            return json.dumps(
                {
                    "jobs": [
                        {
                            "id": "job-1",
                            "payload": {
                                "kind": "systemEvent",
                                "text": '{"kind":"twinbox.schedule","job":"nightly-full"}',
                            },
                        },
                        {
                            "id": "job-2",
                            "payload": {
                                "kind": "systemEvent",
                                "text": '{"kind":"twinbox.schedule","job":"nightly-full"}',
                            },
                        },
                    ]
                },
                ensure_ascii=False,
            )
        raise AssertionError(f"Unexpected argv: {argv}")

    try:
        schedule_override.sync_schedule_to_openclaw(
            job_name="nightly-full-refresh",
            cron="0 2 * * *",
            timezone="Asia/Shanghai",
            runner=fake_runner,
        )
    except ValueError as exc:
        assert "Multiple OpenClaw cron jobs" in str(exc)
    else:
        raise AssertionError("Expected duplicate Twinbox cron jobs to raise ValueError")
