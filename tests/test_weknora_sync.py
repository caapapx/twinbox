"""Local TDD contract for the optional WeKnora retrieval adapter.

These tests use a fake capability port only.  They neither discover a real API
nor create a KB, write remote data, or access a mailbox.
"""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest

from twinbox_core.evidence_contract import SourceGrant
from twinbox_core.weknora import (
    WeKnoraSyncError,
    build_sync_payload,
    load_sync_state,
    revoke_excerpt,
    search_excerpts,
    sync_excerpt,
    sync_state_path,
)


class FakeProvider:
    """Capability-port fake; intentionally unrelated to a real WeKnora API."""

    def __init__(self) -> None:
        self.lookup_results: list[dict[str, str]] = []
        self.create_result: dict[str, str] | BaseException = {
            "status": "accepted",
            "knowledge_ref": "knowledge-1",
            "parse_state": "pending",
        }
        self.update_result: dict[str, str] = {"status": "accepted", "parse_state": "pending"}
        self.delete_result: dict[str, str] | BaseException = {"status": "deleted"}
        self.search_result: dict[str, object] = {"status": "ok", "coverage": "complete", "hits": []}
        self.lookups: list[tuple[str, str]] = []
        self.creates: list[tuple[str, str, dict[str, object], str]] = []
        self.updates: list[tuple[str, str, str, dict[str, object]]] = []
        self.deletes: list[tuple[str, str]] = []
        self.searches: list[tuple[str, str, dict[str, object]]] = []

    def lookup_by_source_key(self, scope: str, stable_key: str) -> dict[str, str]:
        self.lookups.append((scope, stable_key))
        if self.lookup_results:
            return self.lookup_results.pop(0)
        return {"status": "missing"}

    def create_excerpt(
        self,
        scope: str,
        stable_key: str,
        payload: dict[str, object],
        attempt_id: str,
    ) -> dict[str, str]:
        self.creates.append((scope, stable_key, deepcopy(payload), attempt_id))
        if isinstance(self.create_result, BaseException):
            raise self.create_result
        return deepcopy(self.create_result)

    def update_excerpt(
        self,
        scope: str,
        knowledge_ref: str,
        expected_hash: str,
        payload: dict[str, object],
    ) -> dict[str, str]:
        self.updates.append((scope, knowledge_ref, expected_hash, deepcopy(payload)))
        return deepcopy(self.update_result)

    def delete_excerpt(self, scope: str, knowledge_ref: str) -> dict[str, str]:
        self.deletes.append((scope, knowledge_ref))
        if isinstance(self.delete_result, BaseException):
            raise self.delete_result
        return deepcopy(self.delete_result)

    def search(
        self, scope: str, query: str, authorized_filter: dict[str, object],
        _classification_filter: object, _limit: int, _deadline: float,
    ) -> dict[str, object]:
        self.searches.append((scope, query, deepcopy(authorized_filter)))
        return deepcopy(self.search_result)


def _grant(scope: str = "scope-a", *, enabled: bool = True) -> SourceGrant:
    return SourceGrant(
        scope_id=scope,
        account_ref="account-a",
        mail_refs=frozenset({"mail-a"}),
        enabled=enabled,
    )


def _source(*, excerpt: str = "original body evidence", scope: str = "scope-a") -> dict[str, str]:
    return {
        "scope_id": scope,
        "account_ref": "account-a",
        "mail_ref": "mail-a",
        "message_id": "<message-a@example.invalid>",
        "subject": "Budget review with a subject that must remain metadata",
        "sender": "person@example.invalid",
        "date": "2026-09-20T09:00:00Z",
        "folder": "INBOX",
        "thread_key": "budget-review",
        "original_excerpt": excerpt,
        # This field simulates a pre-existing analysis product. It must never
        # become the KB's claimed source excerpt.
        "inferred_excerpt": "LLM why/action_hint that must never leave TwinBox",
        "classification": {"primary_event_type": "contract_review"},
    }


def test_payload_is_bounded_original_source_and_allowlisted():
    payload = build_sync_payload(_grant(), _source(excerpt="source-only " + "文" * 600))

    assert payload["channel"] == "twinbox"
    assert payload["source"]["scope_id"] == "scope-a"
    assert payload["source"]["mail_ref"] == "mail-a"
    assert payload["stable_title_key"].startswith("tbx_")
    assert "Budget" not in payload["stable_title_key"]
    assert len(payload["excerpt"]) == 512
    assert payload["excerpt"].startswith("source-only ")
    assert "why/action_hint" not in json.dumps(payload, ensure_ascii=False)
    assert "classification" not in json.dumps(payload, ensure_ascii=False)
    assert "inferred_excerpt" not in json.dumps(payload, ensure_ascii=False)
    assert len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= 32 * 1024


@pytest.mark.parametrize(
    ("grant", "source", "reason"),
    [
        (_grant(), {**_source(), "scope_id": ""}, "source_scope_invalid"),
        (_grant(), {**_source(), "scope_id": "scope-b"}, "scope_mismatch"),
        (_grant(), {**_source(), "mail_ref": ""}, "source_identity_invalid"),
        (_grant(), {**_source(), "mail_ref": "mail-b"}, "reference_forbidden"),
    ],
)
def test_missing_or_untrusted_scope_identity_is_rejected(grant, source, reason):
    with pytest.raises(WeKnoraSyncError, match=reason):
        build_sync_payload(grant, source)


def test_same_content_skips_and_changed_content_updates(tmp_path: Path):
    provider = FakeProvider()
    first = sync_excerpt(tmp_path, provider, _grant(), _source())
    second = sync_excerpt(tmp_path, provider, _grant(), _source())
    changed = sync_excerpt(tmp_path, provider, _grant(), _source(excerpt="new original evidence"))

    assert first["status"] == "created"
    assert second["status"] == "skipped"
    assert changed["status"] == "updated"
    assert len(provider.creates) == 1
    assert len(provider.updates) == 1
    assert provider.creates[0][2]["excerpt"] == "original body evidence"
    assert provider.updates[0][3]["excerpt"] == "new original evidence"
    state = load_sync_state(tmp_path)
    entry = next(iter(state["mappings"].values()))
    assert entry["knowledge_ref"] == "knowledge-1"
    assert entry["sync_state"] == "parsing"
    assert entry["parse_state"] == "pending"


def test_create_timeout_is_uncertain_then_lookup_reconciles_without_second_create(tmp_path: Path):
    provider = FakeProvider()
    provider.create_result = TimeoutError("provider response body must not be stored")
    uncertain = sync_excerpt(tmp_path, provider, _grant(), _source())

    assert uncertain["status"] == "uncertain"
    assert len(provider.creates) == 1
    state_after_timeout = load_sync_state(tmp_path)
    entry_after_timeout = next(iter(state_after_timeout["mappings"].values()))
    assert entry_after_timeout["sync_state"] == "uncertain"
    assert entry_after_timeout["knowledge_ref"] is None
    assert entry_after_timeout["last_error_code"] == "provider_timeout"

    provider.lookup_results = [{"status": "found", "knowledge_ref": "knowledge-from-reconcile"}]
    reconciled = sync_excerpt(tmp_path, provider, _grant(), _source())

    assert reconciled["status"] == "reconciled"
    assert reconciled["knowledge_ref"] == "knowledge-from-reconcile"
    assert len(provider.creates) == 1
    state = load_sync_state(tmp_path)
    entry = next(iter(state["mappings"].values()))
    assert entry["knowledge_ref"] == "knowledge-from-reconcile"
    assert entry["sync_state"] == "parsing"


def test_lookup_conflict_quarantines_instead_of_creating(tmp_path: Path):
    provider = FakeProvider()
    provider.lookup_results = [{"status": "conflict"}]

    result = sync_excerpt(tmp_path, provider, _grant(), _source())

    assert result == {"status": "quarantined", "error": "source_key_conflict"}
    assert provider.creates == []
    entry = next(iter(load_sync_state(tmp_path)["mappings"].values()))
    assert entry["sync_state"] == "quarantined"
    assert entry["last_error_code"] == "source_key_conflict"


def test_state_and_journal_do_not_persist_source_excerpt_or_provider_exception(tmp_path: Path):
    provider = FakeProvider()
    provider.create_result = TimeoutError("provider response body must not be stored")
    source = _source(excerpt="very private original excerpt")
    sync_excerpt(tmp_path, provider, _grant(), source)

    stored = sync_state_path(tmp_path).read_text(encoding="utf-8")
    assert "very private original excerpt" not in stored
    assert "provider response body" not in stored
    assert "inferred_excerpt" not in stored
    assert load_sync_state(tmp_path)["journal"][-1]["state"] == "uncertain"


def test_config_is_disabled_by_default_and_never_projects_provider_details(tmp_path: Path, monkeypatch):
    from twinbox_core.config import get_weknora_config, save_config

    monkeypatch.setenv("TWINBOX_STATE_ROOT", str(tmp_path))
    assert get_weknora_config() == {
        "enabled": False,
        "adr_004_accepted": False,
        "provider_port_verified": False,
        "live_operations_available": False,
    }
    save_config({"weknora": {"enabled": True, "endpoint": "http://secret.invalid", "api_key": "not-for-output"}})
    assert get_weknora_config() == {
        "enabled": True,
        "adr_004_accepted": False,
        "provider_port_verified": False,
        "live_operations_available": False,
    }


def test_cli_weknora_status_and_sync_are_explicitly_safe_when_disabled(tmp_path: Path, monkeypatch):
    from twinbox_core import cli

    monkeypatch.setattr(cli, "_account_root", lambda account_id=None: tmp_path)
    monkeypatch.setattr(cli, "_resolved_account_id", lambda account_id=None: "account-a")
    monkeypatch.setattr(cli, "get_weknora_config", lambda: {
        "enabled": False,
        "provider_port_verified": False,
        "live_operations_available": False,
    })

    status = cli.cmd_weknora(["status"], account_id="account-a")
    blocked = cli.cmd_weknora(["sync", "--payload-json", json.dumps(_source())], account_id="account-a")
    revoke_usage = cli.cmd_weknora(["revoke"], account_id="account-a")

    assert status["ok"] is True
    assert status["data"]["enabled"] is False
    assert status["data"]["live_provider_available"] is False
    assert blocked == {"ok": False, "error": "weknora_disabled", "recovery_tool": "twinbox_status"}
    assert revoke_usage == {"ok": False, "error": "weknora_usage", "recovery_tool": "twinbox_status"}
    assert not sync_state_path(tmp_path).exists()


def _payload_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_crash_recovery_reconciles_precommitted_upload_before_another_create(tmp_path: Path):
    provider = FakeProvider()
    provider.create_result = TimeoutError("synthetic response loss")
    assert sync_excerpt(tmp_path, provider, _grant(), _source())["status"] == "uncertain"
    payload_hash = _payload_hash(provider.creates[0][2])
    state = load_sync_state(tmp_path)
    entry = next(iter(state["mappings"].values()))
    # Model a crash after the remote accepted a write, but before the local
    # success transition committed.  The intent journal/state remains durable.
    entry.update({"sync_state": "uploading", "last_error_code": None, "pending_operation": "create"})
    sync_state_path(tmp_path).write_text(json.dumps(state), encoding="utf-8")
    provider.lookup_results = [{
        "status": "found", "knowledge_ref": "knowledge-after-crash", "excerpt_hash": payload_hash,
        "parse_state": "ready",
    }]

    recovered = sync_excerpt(tmp_path, provider, _grant(), _source())

    assert recovered == {"status": "reconciled", "knowledge_ref": "knowledge-after-crash", "parse_state": "ready"}
    assert len(provider.creates) == 1
    assert load_sync_state(tmp_path)["journal"][-1]["state"] == "uploaded"


def test_lost_mapping_reconciles_remote_identity_before_create(tmp_path: Path):
    provider = FakeProvider()
    created = sync_excerpt(tmp_path, provider, _grant(), _source())
    assert created["status"] == "created"
    payload_hash = _payload_hash(provider.creates[0][2])
    sync_state_path(tmp_path).unlink()
    provider.lookup_results = [{
        "status": "found", "knowledge_ref": "knowledge-1", "excerpt_hash": payload_hash,
        "parse_state": "ready",
    }]

    reconciled = sync_excerpt(tmp_path, provider, _grant(), _source())

    assert reconciled["status"] == "reconciled"
    assert len(provider.creates) == 1
    assert next(iter(load_sync_state(tmp_path)["mappings"].values()))["knowledge_ref"] == "knowledge-1"


def test_single_state_writer_serializes_concurrent_same_source_create(tmp_path: Path):
    class SlowProvider(FakeProvider):
        def create_excerpt(self, *args, **kwargs):
            time.sleep(0.03)
            return super().create_excerpt(*args, **kwargs)

    provider = SlowProvider()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: sync_excerpt(tmp_path, provider, _grant(), _source()), range(2)))

    assert sorted(result["status"] for result in results) == ["created", "skipped"]
    assert len(provider.creates) == 1


def test_second_declared_writer_is_isolated_from_existing_account_state(tmp_path: Path):
    provider = FakeProvider()
    assert sync_excerpt(tmp_path, provider, _grant(), _source(), writer_id="writer-a")["status"] == "created"

    with pytest.raises(WeKnoraSyncError, match="writer_conflict"):
        sync_excerpt(tmp_path, provider, _grant(), _source(), writer_id="writer-b")

    assert len(provider.creates) == 1


def test_revoke_hides_before_delete_and_delete_failure_never_restores_visibility(tmp_path: Path):
    provider = FakeProvider()
    assert sync_excerpt(tmp_path, provider, _grant(), _source())["status"] == "created"
    provider.delete_result = {"status": "failed"}

    failed = revoke_excerpt(tmp_path, provider, _grant(enabled=False), mail_ref="mail-a")

    assert failed == {"status": "delete_pending", "error": "provider_failed"}
    entry = next(iter(load_sync_state(tmp_path)["mappings"].values()))
    assert entry["visibility"] == "hidden"
    assert entry["sync_state"] == "delete_pending"
    assert entry["last_error_code"] == "provider_failed"
    assert search_excerpts(tmp_path, provider, _grant(), "must stay hidden") == {
        "status": "no_authorized_sources",
        "hits": [],
        "coverage": {"remote": "unknown", "classification": "unknown"},
        "diagnostics": ["no_authorized_sources"],
    }
    assert provider.searches == []
    with pytest.raises(WeKnoraSyncError, match="source_revoked"):
        sync_excerpt(tmp_path, provider, _grant(), _source())

    provider.delete_result = {"status": "deleted"}
    deleted = revoke_excerpt(tmp_path, provider, _grant(enabled=False), mail_ref="mail-a")
    assert deleted == {"status": "deleted"}
    assert len(provider.deletes) == 2
    assert next(iter(load_sync_state(tmp_path)["mappings"].values()))["sync_state"] == "deleted"
