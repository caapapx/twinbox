"""Local TDD contract for the optional WeKnora retrieval capability.

All providers and source records in this file are fakes.  The tests exercise
only the local adapter boundary; they never discover or invoke a real WeKnora
API, mailbox, KB, source grant, or network service.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from twinbox_core.classification_store import publish_classifications
from twinbox_core.evidence_contract import SourceGrant
from twinbox_core.weknora import search_excerpts, sync_excerpt


class FakeSearchProvider:
    """Fake capability port, deliberately not a model of a product API."""

    def __init__(self) -> None:
        self.search_result: dict[str, Any] | BaseException = {
            "status": "ok", "coverage": "complete", "hits": []
        }
        self.searches: list[tuple[str, str, dict[str, object], object, int, float]] = []
        self.creates: list[tuple[str, str]] = []

    def lookup_by_source_key(self, _scope: str, _stable_key: str) -> dict[str, str]:
        return {"status": "missing"}

    def create_excerpt(
        self,
        scope: str,
        _stable_key: str,
        payload: dict[str, object],
        _attempt_id: str,
    ) -> dict[str, str]:
        self.creates.append((scope, str(payload["source"]["mail_ref"])))
        return {
            "status": "accepted",
            "knowledge_ref": f"knowledge-{payload['source']['mail_ref']}",
            "parse_state": "ready",
        }

    def update_excerpt(
        self,
        _scope: str,
        _knowledge_ref: str,
        _expected_hash: str,
        _payload: dict[str, object],
    ) -> dict[str, str]:
        return {"status": "accepted", "parse_state": "ready"}

    def search(
        self,
        scope: str,
        query: str,
        authorized_filter: dict[str, object],
        classification_filter: object,
        limit: int,
        deadline: float,
    ) -> dict[str, Any]:
        self.searches.append((scope, query, deepcopy(authorized_filter), classification_filter, limit, deadline))
        if isinstance(self.search_result, BaseException):
            raise self.search_result
        return deepcopy(self.search_result)


def _grant(
    mail_refs: frozenset[str] = frozenset({"mail-a"}),
    *,
    scope: str = "scope-a",
    account: str = "account-a",
    enabled: bool = True,
) -> SourceGrant:
    return SourceGrant(scope_id=scope, account_ref=account, mail_refs=mail_refs, enabled=enabled)


def _source(mail_ref: str, thread_key: str) -> dict[str, str]:
    return {
        "scope_id": "scope-a",
        "account_ref": "account-a",
        "mail_ref": mail_ref,
        "subject": f"Synthetic subject for {mail_ref}",
        "sender": "synthetic@example.invalid",
        "date": "2026-09-20T09:00:00Z",
        "folder": "INBOX",
        "thread_key": thread_key,
        "original_excerpt": f"Synthetic original evidence for {mail_ref}",
    }


def _seed_mappings(root: Path, provider: FakeSearchProvider) -> None:
    grant = _grant(frozenset({"mail-a", "mail-b"}))
    assert sync_excerpt(root, provider, grant, _source("mail-a", "thread-a"))["status"] == "created"
    assert sync_excerpt(root, provider, grant, _source("mail-b", "thread-b"))["status"] == "created"


def test_search_pre_filters_grant_then_joins_classification_and_mapping(tmp_path: Path):
    provider = FakeSearchProvider()
    _seed_mappings(tmp_path, provider)
    snapshot = publish_classifications(
        tmp_path,
        scope_id="scope-a",
        cases=[{"case_key": "contract-a", "mail_refs": ["mail-a"]}],
        classifications=[{
            "case_key": "contract-a",
            "status": "classified",
            "primary_event_type": "contract.review",
            "tags": {"workstream": ["legal"]},
        }],
        coverage={"state": "complete", "window": {"since": "2026-09-01", "until": "2026-09-20"}},
        pack_fingerprint="synthetic-pack",
        classifier_version="synthetic-classifier",
        source_revision=1,
        observed_at="2026-09-20T09:00:00Z",
    )
    case_ref = snapshot["active_snapshot"]["cases"][0]["case_ref"]
    provider.search_result = {
        "status": "ok",
        "coverage": "complete",
        "hits": [
            {"knowledge_ref": "knowledge-mail-b", "excerpt": "must be filtered", "score": 0.99},
            {"knowledge_ref": "unmapped", "excerpt": "must also be filtered", "score": 0.98},
            {"knowledge_ref": "knowledge-mail-a", "excerpt": "authorized evidence", "score": 0.73},
        ],
    }

    result = search_excerpts(
        tmp_path,
        provider,
        _grant(),
        "synthetic contract",
        classification_filter={"primary_event_type": "contract.review"},
    )

    assert len(provider.searches) == 1
    scope, query, authorized, sent_filter, limit, deadline = provider.searches[0]
    assert scope == "scope-a"
    assert query == "synthetic contract"
    assert authorized == {
        "scope_id": "scope-a",
        "mail_refs": ("mail-a",),
        "knowledge_refs": ("knowledge-mail-a",),
    }
    assert sent_filter is None  # local 013 join resolves filters before remote search
    assert limit == 5
    assert deadline > 0
    assert result["status"] == "ok"
    assert result["diagnostics"] == ["remote_hits_filtered"]
    assert result["coverage"] == {"remote": "complete", "classification": "complete"}
    assert result["hits"] == [{
        "knowledge_ref": "knowledge-mail-a",
        "mail_ref": "mail-a",
        "thread_key": "thread-a",
        "excerpt": "authorized evidence",
        "retrieval_backend": "weknora",
        "score": 0.73,
        "score_origin": "weknora",
        "classification_coverage": "covered",
        "classification": {"case_refs": [case_ref], "primary_event_types": ["contract.review"]},
        "live_status": None,
    }]


def test_search_returns_unknown_live_status_for_authorized_mail_outside_current_pulse(tmp_path: Path):
    provider = FakeSearchProvider()
    _seed_mappings(tmp_path, provider)
    provider.search_result = {
        "status": "ok", "coverage": "complete",
        "hits": [{"knowledge_ref": "knowledge-mail-a", "excerpt": "older evidence", "score": 0.4}],
    }
    pulse = tmp_path / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
    pulse.parent.mkdir(parents=True)
    pulse.write_text(
        '{"generated_at":"2026-09-20T10:00:00Z","thread_index":['
        '{"latest_message_ref":"mail-b","thread_key":"thread-b","queue_tags":["pending"]}]}',
        encoding="utf-8",
    )

    result = search_excerpts(tmp_path, provider, _grant(), "older synthetic topic")

    assert result["hits"][0]["mail_ref"] == "mail-a"
    assert result["hits"][0]["live_status"] is None
    assert result["hits"][0]["classification_coverage"] == "unknown"


def test_timeout_falls_back_under_same_grant_without_mixing_raw_scores(tmp_path: Path):
    provider = FakeSearchProvider()
    _seed_mappings(tmp_path, provider)
    provider.search_result = TimeoutError("untrusted remote error body")
    fallback_calls: list[tuple[str, frozenset[str], int]] = []

    def fallback(query: str, _root: Path, grant: SourceGrant, *, mail_refs: frozenset[str], limit: int):
        fallback_calls.append((query, mail_refs, limit))
        assert grant.scope_id == "scope-a"
        return [
            {"mail_ref": "mail-b", "thread_key": "thread-b", "excerpt": "must be filtered", "score": 0.9},
            {"mail_ref": "mail-a", "thread_key": "thread-a", "excerpt": "fallback evidence", "score": 0.2},
        ]

    result = search_excerpts(tmp_path, provider, _grant(), "fallback query", fallback=fallback)

    assert fallback_calls == [("fallback query", frozenset({"mail-a"}), 5)]
    assert result["status"] == "fallback"
    assert result["diagnostics"] == ["weknora_timeout", "sidecar_hits_filtered"]
    assert result["hits"] == [{
        "knowledge_ref": "knowledge-mail-a",
        "mail_ref": "mail-a",
        "thread_key": "thread-a",
        "excerpt": "fallback evidence",
        "retrieval_backend": "sidecar",
        "score": 0.2,
        "score_origin": "sidecar",
        "classification_coverage": "unknown",
        "classification": {"case_refs": [], "primary_event_types": []},
        "live_status": None,
    }]


def test_default_sidecar_fallback_pre_filters_activity_pulse_before_matching(tmp_path: Path):
    provider = FakeSearchProvider()
    _seed_mappings(tmp_path, provider)
    provider.search_result = TimeoutError("synthetic timeout")
    pulse = tmp_path / "runtime" / "validation" / "phase-4" / "activity-pulse.json"
    pulse.parent.mkdir(parents=True)
    pulse.write_text(
        '{"generated_at":"2026-09-20T10:00:00Z","thread_index":['
        '{"latest_message_ref":"mail-b","thread_key":"thread-b","latest_subject":"fallback review"},'
        '{"latest_message_ref":"mail-a","thread_key":"thread-a","latest_subject":"fallback review"}]}',
        encoding="utf-8",
    )

    result = search_excerpts(tmp_path, provider, _grant(), "fallback review")

    assert result["status"] == "fallback"
    assert result["diagnostics"] == ["weknora_timeout"]
    assert [hit["mail_ref"] for hit in result["hits"]] == ["mail-a"]
    assert result["hits"][0]["retrieval_backend"] == "sidecar"
    assert result["hits"][0]["score_origin"] == "sidecar"
