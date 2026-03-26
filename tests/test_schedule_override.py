from __future__ import annotations

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
