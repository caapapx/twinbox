"""Tests for openclaw_config_merge (no deploy orchestration)."""

from __future__ import annotations

import json

from twinbox_core.openclaw_config_merge import deep_merge_openclaw, merge_twinbox_openclaw_entry


def test_deep_merge_nested_dict() -> None:
    dst = {"skills": {"entries": {"a": 1}}, "x": 0}
    src = {"skills": {"entries": {"b": 2}}}
    out = deep_merge_openclaw(dst, src)
    assert out["skills"]["entries"] == {"a": 1, "b": 2}
    assert out["x"] == 0


def test_merge_twinbox_sets_enabled() -> None:
    out = merge_twinbox_openclaw_entry({}, dotenv={}, sync_env_from_dotenv=False)
    assert out["skills"]["entries"]["twinbox"]["enabled"] is True
    assert out["skills"]["entries"]["twinbox"]["env"] == {}


def test_merge_twinbox_sync_env_from_dotenv() -> None:
    out = merge_twinbox_openclaw_entry(
        {},
        dotenv={"MAIL_ADDRESS": "u@x.com", "IMAP_HOST": "imap.x"},
        sync_env_from_dotenv=True,
    )
    env = out["skills"]["entries"]["twinbox"]["env"]
    assert env.get("MAIL_ADDRESS") == "u@x.com"
    assert env.get("IMAP_HOST") == "imap.x"


def test_deep_merge_does_not_mutate_inputs() -> None:
    dst = {"a": {"b": 1}}
    src = {"a": {"c": 2}}
    deep_merge_openclaw(dst, src)
    assert dst == {"a": {"b": 1}}
    assert json.dumps(dst) == '{"a": {"b": 1}}'
