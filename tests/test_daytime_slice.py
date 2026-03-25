from __future__ import annotations

import json
from pathlib import Path

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
    _write_json(
        tmp_path / "runtime/validation/phase-1/raw/envelopes-merged.json",
        [
            {
                "id": "301",
                "folder": "INBOX",
                "subject": "客户A部署反馈",
                "date": "2026-03-25T09:00:00+08:00",
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
