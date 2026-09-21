"""Authorization and fail-closed local TDD contract for WeKnora retrieval."""
from __future__ import annotations

from pathlib import Path

import pytest

from twinbox_core.evidence_contract import SourceGrant
from twinbox_core.weknora import WeKnoraSyncError, search_excerpts, sync_excerpt

from test_weknora_search import FakeSearchProvider, _grant, _seed_mappings


def test_revoked_grant_rejects_before_remote_or_sidecar(tmp_path: Path):
    provider = FakeSearchProvider()
    _seed_mappings(tmp_path, provider)
    fallback_calls = 0

    def fallback(*_args, **_kwargs):
        nonlocal fallback_calls
        fallback_calls += 1
        return []

    with pytest.raises(WeKnoraSyncError, match="source_disabled"):
        search_excerpts(
            tmp_path,
            provider,
            _grant(enabled=False),
            "must not search",
            fallback=fallback,
        )

    assert provider.searches == []
    assert fallback_calls == 0


@pytest.mark.parametrize(
    "grant",
    [
        SourceGrant("scope-b", "account-a", frozenset({"mail-a"}), enabled=True),
        SourceGrant("scope-a", "account-b", frozenset({"mail-a"}), enabled=True),
        SourceGrant("scope-a", "account-a", frozenset(), enabled=True),
    ],
)
def test_cross_scope_account_or_empty_grant_has_no_remote_or_sidecar_visibility(tmp_path: Path, grant: SourceGrant):
    provider = FakeSearchProvider()
    _seed_mappings(tmp_path, provider)
    fallback_calls = 0

    def fallback(*_args, **_kwargs):
        nonlocal fallback_calls
        fallback_calls += 1
        return [{"mail_ref": "mail-a", "excerpt": "must never return"}]

    result = search_excerpts(tmp_path, provider, grant, "forbidden query", fallback=fallback)

    assert result == {
        "status": "no_authorized_sources",
        "hits": [],
        "coverage": {"remote": "unknown", "classification": "unknown"},
        "diagnostics": ["no_authorized_sources"],
    }
    assert provider.searches == []
    assert fallback_calls == 0


def test_classification_filter_without_current_013_snapshot_fails_closed(tmp_path: Path):
    provider = FakeSearchProvider()
    _seed_mappings(tmp_path, provider)

    result = search_excerpts(
        tmp_path,
        provider,
        _grant(),
        "filter query",
        classification_filter={"primary_event_type": "contract.review"},
    )

    assert result == {
        "status": "partial",
        "hits": [],
        "coverage": {"remote": "unknown", "classification": "unknown"},
        "diagnostics": ["classification_unavailable"],
    }
    assert provider.searches == []


def test_invalid_filter_is_rejected_before_invoking_provider(tmp_path: Path):
    provider = FakeSearchProvider()
    _seed_mappings(tmp_path, provider)

    with pytest.raises(WeKnoraSyncError, match="classification_filter_invalid"):
        search_excerpts(tmp_path, provider, _grant(), "query", classification_filter={"acl": "bypass"})

    assert provider.searches == []


def test_unmapped_provider_hit_and_oversized_excerpt_do_not_escape_authorized_result(tmp_path: Path):
    provider = FakeSearchProvider()
    _seed_mappings(tmp_path, provider)
    provider.search_result = {
        "status": "ok", "coverage": "complete",
        "hits": [
            {"knowledge_ref": "unknown", "excerpt": "unmapped", "score": 0.8},
            {"knowledge_ref": "knowledge-mail-a", "excerpt": "x" * 513, "score": 0.7},
        ],
        "provider_debug": "untrusted response must not be returned",
    }

    result = search_excerpts(tmp_path, provider, _grant(), "query")

    assert result["status"] == "partial"
    assert result["hits"] == []
    assert result["diagnostics"] == ["remote_hits_filtered"]
    assert "provider_debug" not in result
