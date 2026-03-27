from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from twinbox_core.daytime_slice import build_activity_pulse, search_activity_pulse, write_activity_pulse


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_build_activity_pulse_projects_recent_threads(monkeypatch, tmp_path):
    monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
    _write_json(
        tmp_path / "runtime/validation/phase-1/raw/envelopes-merged.json",
        [
            {
                "id": "101",
                "folder": "INBOX",
                "subject": "项目北辰资源申请",
                "date": "2026-03-24T09:00:00+08:00",
            },
            {
                "id": "102",
                "folder": "INBOX",
                "subject": "Re: 项目北辰资源申请",
                "date": "2026-03-24T10:00:00+08:00",
            },
            {
                "id": "201",
                "folder": "INBOX",
                "subject": "宁夏资源反馈",
                "date": "2026-03-24T08:30:00+08:00",
            },
        ],
    )
    _write_yaml(
        tmp_path / "runtime/validation/phase-4/pending-replies.yaml",
        {
            "generated_at": "2026-03-24T10:05:00+08:00",
            "pending_replies": [
                {
                    "thread_key": "项目北辰资源申请",
                    "flow": "delivery",
                    "waiting_on_me": True,
                    "why": "等待确认资源路径",
                }
            ],
        },
    )

    pulse = build_activity_pulse(window_hours=48, top_k=3)

    assert pulse["summary"]["tracked_threads"] == 2
    assert pulse["summary"]["notifiable_count"] >= 1
    assert pulse["notifiable_items"][0]["thread_key"] == "项目北辰资源申请"
    assert "pending" in pulse["notifiable_items"][0]["queue_tags"]


def test_write_activity_pulse_updates_dedupe_and_suppresses_duplicate(monkeypatch, tmp_path):
    monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
    recent = (datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(hours=1)).isoformat(timespec="seconds")
    _write_json(
        tmp_path / "runtime/validation/phase-1/raw/envelopes-merged.json",
        [
            {
                "id": "301",
                "folder": "INBOX",
                "subject": "客户A部署反馈",
                "date": recent,
            }
        ],
    )

    first_pulse, pulse_path = write_activity_pulse(top_k=3, update_dedupe=True)
    assert pulse_path.is_file()
    assert len(first_pulse["notifiable_items"]) == 1

    second_pulse = build_activity_pulse(top_k=3)
    assert second_pulse["notifiable_items"] == []


def test_search_activity_pulse_supports_thread_key_and_business_keyword(monkeypatch, tmp_path):
    monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
    _write_json(
        tmp_path / "runtime/validation/phase-1/raw/envelopes-merged.json",
        [
            {
                "id": "401",
                "folder": "INBOX",
                "subject": "宁夏fdz现场国化资源申请",
                "date": "2026-03-24T11:00:00+08:00",
            }
        ],
    )
    write_activity_pulse(top_k=3, update_dedupe=False)

    by_keyword = search_activity_pulse("宁夏")
    by_thread_key = search_activity_pulse("宁夏fdz现场国化资源申请")

    assert by_keyword
    assert by_thread_key
    assert by_keyword[0]["thread_key"] == "宁夏fdz现场国化资源申请"
    assert by_thread_key[0]["thread_key"] == "宁夏fdz现场国化资源申请"


def test_build_activity_pulse_filters_dismissed_threads(monkeypatch, tmp_path):
    monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
    _write_json(
        tmp_path / "runtime/validation/phase-1/raw/envelopes-merged.json",
        [
            {
                "id": "501",
                "folder": "INBOX",
                "subject": "项目北辰资源申请",
                "date": "2026-03-26T10:00:00+08:00",
            }
        ],
    )
    _write_yaml(
        tmp_path / "runtime/context/user-queue-state.yaml",
        {
            "dismissed": [
                {
                    "thread_key": "项目北辰资源申请",
                    "dismissed_at": "2026-03-26T10:05:00+08:00",
                    "reason": "已看过",
                    "dismissed_from_queue": "pending",
                    "snapshot": {
                        "latest_message_ref": "INBOX#501",
                        "message_count": 1,
                        "fingerprint": "INBOX#501||||",
                        "last_activity_at": "2026-03-26T10:00:00+08:00",
                    },
                }
            ],
            "completed": [],
        },
    )

    pulse = build_activity_pulse(top_k=3)

    assert pulse["notifiable_items"] == []
    assert pulse["thread_index"] == []


def test_build_activity_pulse_reactivates_dismissed_thread_on_new_fingerprint(monkeypatch, tmp_path):
    monkeypatch.setenv("TWINBOX_CANONICAL_ROOT", str(tmp_path))
    _write_json(
        tmp_path / "runtime/validation/phase-1/raw/envelopes-merged.json",
        [
            {
                "id": "601",
                "folder": "INBOX",
                "subject": "项目北辰资源申请",
                "date": "2026-03-26T10:30:00+08:00",
            }
        ],
    )
    _write_yaml(
        tmp_path / "runtime/context/user-queue-state.yaml",
        {
            "dismissed": [
                {
                    "thread_key": "项目北辰资源申请",
                    "dismissed_at": "2026-03-26T10:05:00+08:00",
                    "reason": "已看过",
                    "dismissed_from_queue": "pending",
                    "snapshot": {
                        "latest_message_ref": "INBOX#500",
                        "message_count": 1,
                        "fingerprint": "INBOX#500||||",
                        "last_activity_at": "2026-03-26T10:00:00+08:00",
                    },
                }
            ],
            "completed": [],
        },
    )

    pulse = build_activity_pulse(top_k=3)

    assert pulse["thread_index"][0]["thread_key"] == "项目北辰资源申请"
    payload = yaml.safe_load((tmp_path / "runtime/context/user-queue-state.yaml").read_text(encoding="utf-8"))
    assert payload["dismissed"] == []


def test_coerce_daytime_state_root_explicit(tmp_path: Path) -> None:
    from twinbox_core.daytime_slice import coerce_daytime_state_root

    nested = tmp_path / "nested"
    nested.mkdir()
    assert coerce_daytime_state_root(nested) == nested.resolve()


def test_coerce_daytime_state_root_none_uses_paths_resolve(monkeypatch, tmp_path: Path) -> None:
    from twinbox_core.daytime_slice import coerce_daytime_state_root

    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
    assert coerce_daytime_state_root(None) == tmp_path.resolve()
