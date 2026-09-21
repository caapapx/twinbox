"""HTTP provider mapping tests for the optional WeKnora live wiring.

Every test uses an injected fake transport: no network, no mailbox, no real
credentials.  Live REST shapes below mirror the verified 2026-09-21 behavior
(manual defaults to draft, publish needs a full PUT, per-doc status polling).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from twinbox_core.evidence_contract import SourceGrant
from twinbox_core.weknora import WeKnoraSyncError
from twinbox_core.weknora_http import (
    HttpWeKnoraProvider,
    build_http_provider,
    live_authorized,
)

BASE = "http://weknora.test/api/v1"
KB = "kb-mail-1"


class FakeTransport:
    """Canned (status, json) per (method, path); records every call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.routes: dict[tuple[str, str], object] = {}

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({
            "method": method, "url": url, "headers": dict(headers),
            "body": json.loads(body.decode("utf-8")) if body else None,
            "timeout": timeout,
        })
        path = url[len(BASE):] if url.startswith(BASE) else url
        outcome = self.routes.get((method, path))
        if outcome is None:
            raise AssertionError(f"unexpected {method} {path}")
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _provider(transport, **extra):
    return HttpWeKnoraProvider(
        base_url=BASE, api_key="test-key", kb_id=KB, transport=transport, **extra,
    )


def _grant(**extra):
    row = {"scope_id": "scope-a", "account_ref": "account-a",
           "mail_refs": frozenset({"mail-a"}), "enabled": True}
    row.update(extra)
    return SourceGrant(**row)


def test_factory_requires_credentials_kb_and_clean_base(monkeypatch, tmp_path):
    for var in ("WEKNORA_BASE_URL", "WEKNORA_API_KEY", "WEKNORA_KB_ID", "WEKNORA_DELETE_PATH"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(WeKnoraSyncError, match="weknora_credentials_missing"):
        build_http_provider()
    monkeypatch.setenv("WEKNORA_BASE_URL", BASE)
    with pytest.raises(WeKnoraSyncError, match="weknora_credentials_missing"):
        build_http_provider()
    monkeypatch.setenv("WEKNORA_API_KEY", "env-secret-key")
    with pytest.raises(WeKnoraSyncError, match="weknora_kb_unconfigured"):
        build_http_provider()
    provider = build_http_provider(kb_id=KB)
    assert provider._base_url == BASE
    assert provider._kb_id == KB
    assert provider._delete_knowledge_path == "/knowledge/{ref}"
    assert "env-secret-key" not in repr(provider)
    monkeypatch.setenv("WEKNORA_DELETE_PATH", "/custom/{ref}")
    assert build_http_provider(kb_id=KB)._delete_knowledge_path == "/custom/{ref}"


def test_lookup_missing_found_and_conflict():
    transport = FakeTransport()
    transport.routes[("GET", f"/knowledge-bases/{KB}/knowledge")] = (200, {"data": [
        {"id": "doc-other", "title": "other", "channel": "twinbox"},
        {"id": "doc-alien", "title": "scope-a::account-a::mail-a", "channel": "agentos-meetings"},
    ]})
    provider = _provider(transport)
    assert provider.lookup_by_source_key("scope-a", "scope-a::account-a::mail-a") == {"status": "missing"}

    transport.routes[("GET", f"/knowledge-bases/{KB}/knowledge")] = (200, {"data": [
        {"id": "doc-1", "title": "scope-a::account-a::mail-a", "channel": "twinbox"},
    ]})
    found = provider.lookup_by_source_key("scope-a", "scope-a::account-a::mail-a")
    assert found["status"] == "found"
    assert found["knowledge_ref"] == "doc-1"

    transport.routes[("GET", f"/knowledge-bases/{KB}/knowledge")] = (200, {"data": [
        {"id": "doc-1", "title": "scope-a::account-a::mail-a", "channel": "twinbox"},
        {"id": "doc-2", "title": "scope-a::account-a::mail-a", "channel": "twinbox"},
    ]})
    assert provider.lookup_by_source_key("scope-a", "scope-a::account-a::mail-a") == {"status": "conflict"}

    sent = transport.calls[0]["headers"]
    assert sent["X-API-Key"] == "test-key"
    assert sent["X-Request-ID"]


def test_create_posts_manual_then_publishes():
    transport = FakeTransport()
    transport.routes[("POST", f"/knowledge-bases/{KB}/knowledge/manual")] = (200, {"data": {"id": "doc-9"}})
    transport.routes[("PUT", "/knowledge/manual/doc-9")] = (200, {"data": {"id": "doc-9"}})
    provider = _provider(transport)
    result = provider.create_excerpt("scope-a", "scope-a::account-a::mail-a",
                                     {"channel": "twinbox", "excerpt": "hello",
                                      "stable_title_key": "scope-a::account-a::mail-a",
                                      "metadata": {"subject": "s"}, "source": {}},
                                     "attempt-1")
    assert result == {"status": "accepted", "knowledge_ref": "doc-9", "parse_state": "pending"}
    assert [call["method"] for call in transport.calls] == ["POST", "PUT"]
    assert transport.calls[1]["body"]["status"] == "publish"
    assert transport.calls[1]["body"]["title"] == "scope-a::account-a::mail-a"


def test_create_timeout_and_forbidden_mapping():
    transport = FakeTransport()
    transport.routes[("POST", f"/knowledge-bases/{KB}/knowledge/manual")] = TimeoutError("provider_timeout")
    with pytest.raises(TimeoutError):
        _provider(transport).create_excerpt("s", "k", {"excerpt": "x"}, "a")

    transport.routes[("POST", f"/knowledge-bases/{KB}/knowledge/manual")] = (403, {"error": "Forbidden"})
    with pytest.raises(WeKnoraSyncError, match="provider_failed"):
        _provider(transport).create_excerpt("s", "k", {"excerpt": "x"}, "a")

    transport.routes[("POST", f"/knowledge-bases/{KB}/knowledge/manual")] = (200, "not-a-mapping")
    with pytest.raises(WeKnoraSyncError, match="provider_response_invalid"):
        _provider(transport).create_excerpt("s", "k", {"excerpt": "x"}, "a")


def test_update_publishes_full_payload():
    transport = FakeTransport()
    transport.routes[("PUT", "/knowledge/manual/doc-1")] = (200, {"data": {"id": "doc-1"}})
    result = _provider(transport).update_excerpt("scope-a", "doc-1", "hash-1", {"excerpt": "new"})
    assert result == {"status": "accepted", "parse_state": "pending"}
    assert transport.calls[0]["body"]["status"] == "publish"


def test_parse_status_mapping_and_missing_doc():
    transport = FakeTransport()
    for raw, expected in (("completed", "ready"), ("processing", "pending"),
                          ("finalizing", "pending"), ("failed", "failed")):
        transport.routes[("GET", "/knowledge/doc-1")] = (200, {"data": {"id": "doc-1", "parse_status": raw}})
        assert _provider(transport).get_parse_status("scope-a", "doc-1") == {"parse_state": expected}
    transport.routes[("GET", "/knowledge/doc-1")] = (404, {"error": "not found"})
    assert _provider(transport).get_parse_status("scope-a", "doc-1") == {"parse_state": "unknown"}


def test_search_maps_hits_and_truncates_excerpt():
    transport = FakeTransport()
    transport.routes[("POST", f"/knowledge-bases/{KB}/hybrid-search")] = (200, {"data": [
        {"knowledge_id": "doc-1", "matched_content": "x" * 600, "score": 0.5},
        {"knowledge_id": "doc-2", "matched_content": "ok", "score": 0.1},
    ]})
    result = _provider(transport).search("scope-a", "q", {"scope_id": "scope-a"}, None, 5, 9999999999.0)
    assert result["status"] == "ok"
    assert result["coverage"] == "complete"
    assert result["hits"][0]["knowledge_ref"] == "doc-1"
    assert len(result["hits"][0]["excerpt"]) <= 512
    assert result["hits"][1]["excerpt"] == "ok"
    assert transport.calls[0]["body"]["query_text"] == "q"


def test_delete_maps_async_task_pending_and_404_absent():
    transport = FakeTransport()
    transport.routes[("DELETE", "/knowledge/doc-1")] = (
        200, {"success": True, "data": {"task_id": "task-1"}},
    )
    assert _provider(transport).delete_excerpt("scope-a", "doc-1") == {"status": "pending"}

    transport.routes[("DELETE", "/knowledge/doc-1")] = (200, {"success": True})
    assert _provider(transport).delete_excerpt("scope-a", "doc-1") == {"status": "deleted"}

    transport.routes[("DELETE", "/knowledge/doc-1")] = (404, {"error": "not found"})
    assert _provider(transport).delete_excerpt("scope-a", "doc-1") == {"status": "absent"}


def test_live_authorized_needs_enabled_adr_and_grant():
    settings = {"enabled": False, "adr_004_accepted": False,
                "provider_port_verified": False, "live_operations_available": False}
    assert live_authorized(settings=settings, grant=_grant()) is False
    assert live_authorized(settings={**settings, "enabled": True}, grant=_grant()) is False
    assert live_authorized(settings={**settings, "enabled": True, "adr_004_accepted": True},
                            grant=_grant(enabled=False)) is False
    assert live_authorized(settings={**settings, "enabled": True, "adr_004_accepted": True},
                            grant=_grant()) is True
    assert live_authorized(settings={**settings, "enabled": True, "adr_004_accepted": True},
                            grant=_grant(enabled=False), require_grant_enabled=False) is True


def test_config_exposes_adr_flag_default_closed():
    from twinbox_core.config import get_weknora_config
    assert get_weknora_config()["adr_004_accepted"] is False
    assert get_weknora_config()["provider_port_verified"] is False
    assert get_weknora_config()["live_operations_available"] is False


def test_no_secret_values_in_provider_repr_and_errors(tmp_path):
    transport = FakeTransport()
    transport.routes[("GET", f"/knowledge-bases/{KB}/knowledge")] = (500, {"error": "boom"})
    provider = HttpWeKnoraProvider(base_url=BASE, api_key="super-secret", kb_id=KB,
                                   transport=transport)
    assert "super-secret" not in repr(provider)
    with pytest.raises(WeKnoraSyncError, match="provider_failed") as exc:
        provider.lookup_by_source_key("scope-a", "k")
    assert "super-secret" not in str(exc.value)


def _write_grant(root: Path, *, enabled: bool = True) -> None:
    config_dir = root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "source-grant.json").write_text(json.dumps({
        "schema_version": "1.0", "scope_id": "scope-a", "account_ref": "account-a",
        "mail_refs": ["mail-a"], "evidence_refs": [], "enabled": enabled,
    }), encoding="utf-8")


def _sync_source() -> dict[str, str]:
    return {
        "scope_id": "scope-a", "account_ref": "account-a", "mail_ref": "mail-a",
        "original_excerpt": "original body evidence", "subject": "s", "sender": "s",
        "date": "d", "folder": "f", "thread_key": "t",
    }


def test_cli_sync_stays_unavailable_without_grant_or_adr(tmp_path, monkeypatch):
    from twinbox_core import cli

    monkeypatch.setattr(cli, "_account_root", lambda account_id=None: tmp_path)
    monkeypatch.setattr(cli, "_resolved_account_id", lambda account_id=None: "account-a")
    monkeypatch.setattr(cli, "get_weknora_config", lambda: {
        "enabled": True, "adr_004_accepted": True,
        "provider_port_verified": False, "live_operations_available": False,
    })
    calls: list[str] = []
    monkeypatch.setattr("twinbox_core.weknora_http.build_http_provider",
                        lambda **kwargs: calls.append("built"))
    result = cli.cmd_weknora(["sync", "--payload-json", json.dumps(_sync_source())],
                             account_id="account-a")
    assert result == {"ok": False, "error": "weknora_provider_unavailable",
                      "recovery_tool": "twinbox_status"}
    assert calls == []


def test_cli_sync_builds_live_provider_behind_triple_gate(tmp_path, monkeypatch):
    from twinbox_core import cli

    _write_grant(tmp_path)
    monkeypatch.setattr(cli, "_account_root", lambda account_id=None: tmp_path)
    monkeypatch.setattr(cli, "_resolved_account_id", lambda account_id=None: "account-a")
    monkeypatch.setattr(cli, "get_weknora_config", lambda: {
        "enabled": True, "adr_004_accepted": True,
        "provider_port_verified": False, "live_operations_available": False,
    })

    class StubProvider:
        def __init__(self) -> None:
            self.lookups: list[tuple[str, str]] = []

        def lookup_by_source_key(self, scope: str, stable_key: str):
            self.lookups.append((scope, stable_key))
            return {"status": "missing"}

        def create_excerpt(self, scope: str, stable_key: str, payload, attempt_id: str):
            return {"status": "accepted", "knowledge_ref": "knowledge-stub", "parse_state": "pending"}

    stub = StubProvider()
    monkeypatch.setattr("twinbox_core.weknora_http.build_http_provider", lambda **kwargs: stub)
    result = cli.cmd_weknora(["sync", "--payload-json", json.dumps(_sync_source())],
                             account_id="account-a")
    assert result["ok"] is True
    assert result["data"]["status"] == "created"
    assert result["data"]["knowledge_ref"] == "knowledge-stub"
    assert stub.lookups


class _RevokeStub:
    def __init__(self) -> None:
        self.lookups: list[tuple[str, str]] = []
        self.deletes: list[tuple[str, str]] = []

    def lookup_by_source_key(self, scope: str, stable_key: str):
        self.lookups.append((scope, stable_key))
        return {"status": "missing"}

    def create_excerpt(self, scope: str, stable_key: str, payload, attempt_id: str):
        return {"status": "accepted", "knowledge_ref": "knowledge-stub", "parse_state": "pending"}

    def delete_excerpt(self, scope: str, knowledge_ref: str):
        self.deletes.append((scope, knowledge_ref))
        return {"status": "deleted"}


def _cli_root(tmp_path, monkeypatch, **settings):
    from twinbox_core import cli

    monkeypatch.setattr(cli, "_account_root", lambda account_id=None: tmp_path)
    monkeypatch.setattr(cli, "_resolved_account_id", lambda account_id=None: "account-a")
    monkeypatch.setattr(cli, "get_weknora_config", lambda: {
        "enabled": True, "adr_004_accepted": False,
        "provider_port_verified": False, "live_operations_available": False,
        **settings,
    })
    return cli


def test_cli_revoke_requires_mail_ref(tmp_path, monkeypatch):
    cli = _cli_root(tmp_path, monkeypatch)
    assert cli.cmd_weknora(["revoke"], account_id="account-a") == {
        "ok": False, "error": "weknora_usage", "recovery_tool": "twinbox_status",
    }


def test_cli_revoke_hides_then_deletes_even_if_grant_disabled(tmp_path, monkeypatch):
    from twinbox_core.weknora import load_sync_state

    cli = _cli_root(tmp_path, monkeypatch, enabled=True)
    _write_grant(tmp_path)
    stub = _RevokeStub()
    created = cli.cmd_weknora(
        ["sync", "--payload-json", json.dumps(_sync_source())],
        account_id="account-a", provider=stub,
    )
    assert created["data"]["status"] == "created"
    _write_grant(tmp_path, enabled=False)

    revoked = cli.cmd_weknora(
        ["revoke", "--mail-ref", "mail-a"], account_id="account-a", provider=stub,
    )
    assert revoked == {"ok": True, "data": {"status": "deleted"}}
    assert stub.deletes == [("scope-a", "knowledge-stub")]
    entry = next(iter(load_sync_state(tmp_path)["mappings"].values()))
    assert entry["visibility"] == "hidden"
    assert entry["sync_state"] == "deleted"


def test_cli_revoke_hides_without_network_when_live_gate_closed(tmp_path, monkeypatch):
    from twinbox_core.weknora import load_sync_state

    cli = _cli_root(tmp_path, monkeypatch, enabled=True, adr_004_accepted=False)
    _write_grant(tmp_path)
    stub = _RevokeStub()
    assert cli.cmd_weknora(
        ["sync", "--payload-json", json.dumps(_sync_source())],
        account_id="account-a", provider=stub,
    )["data"]["status"] == "created"

    calls: list[str] = []
    monkeypatch.setattr(
        "twinbox_core.weknora_http.build_http_provider",
        lambda **kwargs: calls.append("built"),
    )
    revoked = cli.cmd_weknora(["revoke", "--mail-ref", "mail-a"], account_id="account-a")
    assert calls == []
    assert revoked == {"ok": True, "data": {"status": "delete_pending", "error": "provider_pending"}}
    entry = next(iter(load_sync_state(tmp_path)["mappings"].values()))
    assert entry["visibility"] == "hidden"
    assert entry["sync_state"] == "delete_pending"


def test_cli_revoke_builds_live_provider_after_grant_is_turned_off(tmp_path, monkeypatch):
    cli = _cli_root(tmp_path, monkeypatch, enabled=True, adr_004_accepted=True)
    _write_grant(tmp_path)
    created = _RevokeStub()
    assert cli.cmd_weknora(
        ["sync", "--payload-json", json.dumps(_sync_source())],
        account_id="account-a", provider=created,
    )["data"]["status"] == "created"
    _write_grant(tmp_path, enabled=False)

    live = _RevokeStub()
    monkeypatch.setattr("twinbox_core.weknora_http.build_http_provider", lambda **kwargs: live)
    revoked = cli.cmd_weknora(["revoke", "--mail-ref", "mail-a"], account_id="account-a")
    assert revoked == {"ok": True, "data": {"status": "deleted"}}
    assert live.deletes == [("scope-a", "knowledge-stub")]


def test_cli_revoke_still_hides_when_weknora_flag_is_off(tmp_path, monkeypatch):
    from twinbox_core.weknora import load_sync_state

    cli = _cli_root(tmp_path, monkeypatch, enabled=True)
    _write_grant(tmp_path)
    stub = _RevokeStub()
    assert cli.cmd_weknora(
        ["sync", "--payload-json", json.dumps(_sync_source())],
        account_id="account-a", provider=stub,
    )["data"]["status"] == "created"
    monkeypatch.setattr(cli, "get_weknora_config", lambda: {
        "enabled": False, "adr_004_accepted": False,
        "provider_port_verified": False, "live_operations_available": False,
    })
    revoked = cli.cmd_weknora(
        ["revoke", "--mail-ref", "mail-a"], account_id="account-a", provider=stub,
    )
    assert revoked == {"ok": True, "data": {"status": "deleted"}}
    assert next(iter(load_sync_state(tmp_path)["mappings"].values()))["visibility"] == "hidden"
