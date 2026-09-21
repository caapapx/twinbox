"""Live HTTP implementation of the Spec 014 WeKnora provider port.

This module maps the six ``WeKnoraProvider`` capability methods onto the
verified live REST behavior (manual defaults to draft, publish needs a full
PUT, per-document status polling).  It uses only the standard library, reads
credentials exclusively from explicit arguments or the ``WEKNORA_BASE_URL`` /
``WEKNORA_API_KEY`` / ``WEKNORA_KB_ID`` environment variables (optional
``WEKNORA_DELETE_PATH``), and never logs
key material, URLs with secrets, mail bodies, or response payloads.

Nothing here opens the live path by itself: use :func:`live_authorized`
(enabled flag + ADR-004 acceptance + per-scope source grant) before handing a
built provider to ``sync_excerpt`` / ``search_excerpts`` / ``revoke_excerpt``.
All network access in tests goes through the injectable ``transport``; the
default transport is never exercised by the test suite.
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, Callable
from uuid import uuid4

from .evidence_contract import SourceGrant
from .weknora import MAX_EXCERPT_CHARS, WeKnoraSyncError

DEFAULT_TIMEOUT_SECONDS = 30.0
_PUBLISH_STATUS = "publish"
_TWINBOX_CHANNEL = "twinbox"
# 2026-09-21 probe: DELETE /knowledge/{id} returns 200 + task_id (async);
# list is empty afterwards. Immediate GET may still 200.
DEFAULT_DELETE_PATH = "/knowledge/{ref}"

# Only these parse states are admitted from the wire; anything else degrades
# to unknown instead of inventing a ready/failed verdict.
_PARSE_MAP = {
    "completed": "ready",
    "failed": "failed",
    "cancelled": "failed",
    "processing": "pending",
    "finalizing": "pending",
    "pending": "pending",
    "draft": "pending",
}

Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, Any]]


def _urllib_transport(method: str, url: str, headers: dict[str, str],
                      body: bytes | None, timeout: float) -> tuple[int, Any]:
    """Default stdlib transport. Raises TimeoutError or WeKnoraSyncError only."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            code = int(response.status)
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        try:
            return int(exc.code), json.loads(raw or "{}")
        except ValueError:
            return int(exc.code), {}
    except (TimeoutError, socket.timeout) as exc:
        raise TimeoutError("provider_timeout") from exc
    except OSError as exc:
        raise WeKnoraSyncError("provider_failed") from exc
    try:
        return code, json.loads(raw or "{}")
    except ValueError:
        raise WeKnoraSyncError("provider_response_invalid") from None


def _as_list(value: object) -> list[Mapping[str, object]] | None:
    if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
        return list(value)
    if isinstance(value, Mapping):
        for key in ("items", "list", "knowledge", "data", "records"):
            nested = value.get(key)
            if isinstance(nested, list) and all(isinstance(item, Mapping) for item in nested):
                return list(nested)
    return None


class HttpWeKnoraProvider:
    """WeKnoraProvider over live REST with an injectable transport."""

    def __init__(self, *, base_url: str, api_key: str, kb_id: str,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS,
                 transport: Transport | None = None,
                 delete_knowledge_path: str | None = None) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._kb_id = kb_id
        self._timeout = float(timeout)
        self._transport = transport or _urllib_transport
        template = DEFAULT_DELETE_PATH if delete_knowledge_path is None else delete_knowledge_path
        self._delete_knowledge_path = template.strip() or DEFAULT_DELETE_PATH

    def __repr__(self) -> str:
        return (f"HttpWeKnoraProvider(base_url={self._base_url!r}, "
                f"kb_id={self._kb_id!r}, timeout={self._timeout!r})")

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": self._api_key,
            "X-Request-ID": uuid4().hex,
        }

    def _call(self, method: str, path: str, body: Mapping[str, object] | None = None,
              *, timeout: float | None = None) -> tuple[int, Any]:
        payload = None if body is None else json.dumps(
            body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return self._transport(method, self._base_url + path, self._headers(),
                               payload, self._timeout if timeout is None else timeout)

    def _ok(self, method: str, path: str, body: Mapping[str, object] | None = None,
            *, timeout: float | None = None) -> Any:
        code, parsed = self._call(method, path, body, timeout=timeout)
        if not 200 <= code < 300:
            raise WeKnoraSyncError("provider_failed")
        return parsed

    def lookup_by_source_key(self, scope: str, stable_key: str) -> Mapping[str, object]:
        parsed = self._ok("GET", f"/knowledge-bases/{self._kb_id}/knowledge")
        items = _as_list(parsed.get("data") if isinstance(parsed, Mapping) else parsed)
        if items is None:
            raise WeKnoraSyncError("provider_response_invalid")
        matches = [
            item for item in items
            if item.get("title") == stable_key
            and item.get("channel", _TWINBOX_CHANNEL) in (None, "", _TWINBOX_CHANNEL)
            and isinstance(item.get("id"), str)
        ]
        if not matches:
            return {"status": "missing"}
        if len(matches) > 1:
            return {"status": "conflict"}
        return {"status": "found", "knowledge_ref": matches[0]["id"]}

    def _manual_body(self, stable_key: str, payload: Mapping[str, object]) -> dict[str, object]:
        excerpt = payload.get("excerpt")
        if isinstance(excerpt, str) and excerpt.strip():
            content: str = excerpt
        else:
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
            lines = ["（无原文摘录）"]
            for field in ("subject", "sender", "date"):
                value = metadata.get(field) if isinstance(metadata, Mapping) else None
                if isinstance(value, str) and value.strip():
                    lines.append(f"{field}: {value.strip()}")
            content = "\n".join(lines)
        return {"title": stable_key, "content": content, "channel": _TWINBOX_CHANNEL,
                "status": _PUBLISH_STATUS}

    def create_excerpt(self, scope: str, stable_key: str, payload: Mapping[str, object],
                       attempt_id: str) -> Mapping[str, object]:
        body = self._manual_body(stable_key, payload)
        created = self._ok("POST", f"/knowledge-bases/{self._kb_id}/knowledge/manual",
                           {key: body[key] for key in ("title", "content", "channel")})
        ref = created.get("data", {}).get("id") if isinstance(created, Mapping) else None
        if not isinstance(ref, str) or not ref:
            raise WeKnoraSyncError("provider_response_invalid")
        published = self._ok("PUT", f"/knowledge/manual/{ref}", body)
        if not isinstance(published, Mapping):
            raise WeKnoraSyncError("provider_response_invalid")
        return {"status": "accepted", "knowledge_ref": ref, "parse_state": "pending"}

    def update_excerpt(self, scope: str, knowledge_ref: str, expected_hash: str,
                       payload: Mapping[str, object]) -> Mapping[str, object]:
        title = payload.get("stable_title_key")
        stable_key = title if isinstance(title, str) and title else knowledge_ref
        updated = self._ok("PUT", f"/knowledge/manual/{knowledge_ref}",
                           self._manual_body(stable_key, payload))
        if not isinstance(updated, Mapping):
            raise WeKnoraSyncError("provider_response_invalid")
        return {"status": "accepted", "parse_state": "pending"}

    def get_parse_status(self, scope: str, knowledge_ref: str) -> Mapping[str, object]:
        code, parsed = self._call("GET", f"/knowledge/{knowledge_ref}")
        if code == 404:
            return {"parse_state": "unknown"}
        if not 200 <= code < 300:
            raise WeKnoraSyncError("provider_failed")
        detail = parsed.get("data") if isinstance(parsed, Mapping) else None
        raw = detail.get("parse_status") if isinstance(detail, Mapping) else None
        return {"parse_state": _PARSE_MAP.get(raw, "unknown")}

    def search(self, scope: str, query: str, authorized_filter: Mapping[str, object],
               classification_filter: Mapping[str, object] | None,
               limit: int, deadline: float) -> Mapping[str, object]:
        # Pre-search isolation is the KB path itself; both KBs under one key
        # share an embedding model, but a single provider instance serves one.
        remaining = max(1.0, deadline - time.monotonic())
        parsed = self._ok(
            "POST", f"/knowledge-bases/{self._kb_id}/hybrid-search",
            {"query_text": query, "match_count": max(1, int(limit))},
            timeout=min(self._timeout, remaining),
        )
        items = _as_list(parsed.get("data") if isinstance(parsed, Mapping) else parsed)
        if items is None:
            raise WeKnoraSyncError("provider_response_invalid")
        hits: list[dict[str, object]] = []
        for item in items:
            ref = item.get("knowledge_id")
            if not isinstance(ref, str) or not ref:
                raise WeKnoraSyncError("provider_response_invalid")
            excerpt = item.get("matched_content")
            hit: dict[str, object] = {"knowledge_ref": ref}
            if isinstance(excerpt, str) and excerpt:
                hit["excerpt"] = excerpt[:MAX_EXCERPT_CHARS]
            score = item.get("score")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                hit["score"] = score
            hits.append(hit)
        return {"status": "ok", "coverage": "complete", "hits": hits}

    def delete_excerpt(self, scope: str, knowledge_ref: str) -> Mapping[str, object]:
        code, parsed = self._call(
            "DELETE", self._delete_knowledge_path.format(ref=knowledge_ref),
        )
        if code == 404:
            return {"status": "absent"}
        if not 200 <= code < 300:
            raise WeKnoraSyncError("provider_failed")
        data = parsed.get("data") if isinstance(parsed, Mapping) else None
        if isinstance(data, Mapping) and isinstance(data.get("task_id"), str) and data["task_id"]:
            return {"status": "pending"}
        return {"status": "deleted"}


def build_http_provider(*, base_url: str | None = None, api_key: str | None = None,
                        kb_id: str | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS,
                        transport: Transport | None = None,
                        delete_knowledge_path: str | None = None) -> HttpWeKnoraProvider:
    """Build a live provider from explicit args or standard environment.

    Raises WeKnoraSyncError (never returns a half-configured provider) when
    credentials or the dedicated KB binding are absent.  Values are never
    logged; only presence is ever reported.
    """
    resolved_base = (base_url or os.environ.get("WEKNORA_BASE_URL") or "").strip().rstrip("/")
    resolved_key = (api_key or os.environ.get("WEKNORA_API_KEY") or "").strip()
    if not resolved_base or not resolved_key:
        raise WeKnoraSyncError("weknora_credentials_missing")
    resolved_kb = (kb_id or os.environ.get("WEKNORA_KB_ID") or "").strip()
    if not resolved_kb:
        raise WeKnoraSyncError("weknora_kb_unconfigured")
    resolved_delete = delete_knowledge_path
    if resolved_delete is None:
        resolved_delete = (os.environ.get("WEKNORA_DELETE_PATH") or "").strip() or None
    return HttpWeKnoraProvider(base_url=resolved_base, api_key=resolved_key, kb_id=resolved_kb,
                               timeout=timeout, transport=transport,
                               delete_knowledge_path=resolved_delete)


def live_authorized(*, settings: Mapping[str, object], grant: SourceGrant,
                    require_grant_enabled: bool = True) -> bool:
    """Triple gate for the live path: enabled flag, ADR-004, source grant.

    Any missing leg keeps the deployment on the fake provider / sidecar.  This
    is a code-level AND over three human-owned decisions; it cannot be opened
    by the provider implementation itself.

    Revoke may pass ``require_grant_enabled=False``: turning the grant off must
    still allow a bounded hide-then-delete of copies already created.
    """
    return (settings.get("enabled") is True
            and settings.get("adr_004_accepted") is True
            and (not require_grant_enabled or grant.enabled is True))
