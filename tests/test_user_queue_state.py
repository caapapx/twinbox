from __future__ import annotations

import yaml

from twinbox_core import user_queue_state


def _sample_snapshot(*, fingerprint: str = "INBOX#1|pending|me||open") -> dict[str, object]:
    return {
        "thread_key": "项目北辰资源申请",
        "latest_message_ref": "INBOX#1",
        "message_count": 2,
        "fingerprint": fingerprint,
        "last_activity_at": "2026-03-26T10:00:00+08:00",
    }


def test_dismiss_thread_persists_snapshot_entry(tmp_path):
    user_queue_state.dismiss_thread(
        state_root=tmp_path,
        thread_key="项目北辰资源申请",
        snapshot=_sample_snapshot(),
        reason="已处理",
        dismissed_from_queue="pending",
    )

    payload = yaml.safe_load(
        (tmp_path / "runtime" / "context" / "user-queue-state.yaml").read_text(encoding="utf-8")
    )
    assert payload["dismissed"][0]["thread_key"] == "项目北辰资源申请"
    assert payload["dismissed"][0]["snapshot"]["fingerprint"] == "INBOX#1|pending|me||open"


def test_complete_and_restore_thread_update_state_lists(tmp_path):
    user_queue_state.complete_thread(
        state_root=tmp_path,
        thread_key="项目北辰资源申请",
        snapshot=_sample_snapshot(),
        action_taken="已归档",
    )

    completed = user_queue_state.load_user_queue_state(tmp_path)
    assert completed["completed"][0]["thread_key"] == "项目北辰资源申请"

    user_queue_state.restore_thread(state_root=tmp_path, thread_key="项目北辰资源申请")

    restored = user_queue_state.load_user_queue_state(tmp_path)
    assert restored["completed"] == []
    assert restored["dismissed"] == []


def test_reactivate_dismissed_thread_when_fingerprint_changes(tmp_path):
    user_queue_state.dismiss_thread(
        state_root=tmp_path,
        thread_key="项目北辰资源申请",
        snapshot=_sample_snapshot(fingerprint="INBOX#1|pending|me||open"),
        reason="稍后处理",
        dismissed_from_queue="pending",
    )

    reactivated = user_queue_state.check_reactivation(
        state_root=tmp_path,
        thread_key="项目北辰资源申请",
        fingerprint="INBOX#2|pending|me||open",
    )

    payload = user_queue_state.load_user_queue_state(tmp_path)
    assert reactivated is True
    assert payload["dismissed"] == []


def test_completed_thread_does_not_auto_reactivate(tmp_path):
    user_queue_state.complete_thread(
        state_root=tmp_path,
        thread_key="项目北辰资源申请",
        snapshot=_sample_snapshot(),
        action_taken="已归档",
    )

    reactivated = user_queue_state.check_reactivation(
        state_root=tmp_path,
        thread_key="项目北辰资源申请",
        fingerprint="INBOX#9|pending|me||open",
    )

    payload = user_queue_state.load_user_queue_state(tmp_path)
    assert reactivated is False
    assert payload["completed"][0]["thread_key"] == "项目北辰资源申请"
