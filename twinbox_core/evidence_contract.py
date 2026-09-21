"""013 evidence boundary. Pure validation/construction: no I/O to a mail or KB service.

SourceGrant must come from authenticated configuration, never from the payload.
The packaged schemas are snapshots of specs/013-semantic-policy-projections/contracts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
import json
import re
from typing import Any, Callable, Collection

from twinbox_core.pack import observation_excerpt_action

from jsonschema import Draft202012Validator

MAX_PAYLOAD_BYTES = 32 * 1024
MAX_BATCH_SIZE = 100
_RESERVED = {"acl", "permissions", "roles", "grants", "security", "body", "body_text",
             "full_body", "full_text", "mime", "attachments", "password", "token", "api_key"}
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$")


class EvidenceContractError(ValueError):
    """A bounded, non-sensitive reason code, safe for the tool error envelope."""


@dataclass(frozen=True)
class SourceGrant:
    scope_id: str
    account_ref: str
    mail_refs: frozenset[str] = field(default_factory=frozenset)
    evidence_refs: frozenset[str] = field(default_factory=frozenset)
    enabled: bool = False


@lru_cache(maxsize=2)
def _validator(kind: str) -> Draft202012Validator:
    schema = json.loads(files("twinbox_core").joinpath("schemas", f"{kind}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _validate(payload: object, kind: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise EvidenceContractError("invalid_payload")
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise EvidenceContractError("invalid_json") from None
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise EvidenceContractError("payload_too_large")
    # Return an owned JSON snapshot; callers cannot mutate a validated object by alias.
    value = json.loads(encoded)
    if value.get("schema_version") != "1.0":
        raise EvidenceContractError("unsupported_schema_version")
    if not _validator(kind).is_valid(value):
        raise EvidenceContractError("schema_invalid")
    revision = value["source_revision" if kind == "observation" else "expected_revision"]
    if type(revision) is not int:
        raise EvidenceContractError("revision_invalid")
    return value


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    if not _TIMESTAMP.fullmatch(value):
        raise EvidenceContractError("timestamp_invalid")
    try:
        return datetime.fromisoformat(value.upper().replace("Z", "+00:00"))
    except ValueError:
        raise EvidenceContractError("timestamp_invalid") from None


def _dimensions(mapping: dict[str, Any]) -> None:
    if any(not key.strip() or key.lower() in _RESERVED for key in mapping):
        raise EvidenceContractError("reserved_semantic_key")


def _grant(grant: SourceGrant) -> None:
    if not grant.enabled:
        raise EvidenceContractError("source_disabled")
    if not grant.scope_id or not grant.account_ref:
        raise EvidenceContractError("source_binding_invalid")


def validate_observation(payload: object, *, grant: SourceGrant) -> dict[str, Any]:
    _grant(grant)
    value = _validate(payload, "observation")
    source = value["source"]
    if source["scope_id"] != grant.scope_id or source["account_ref"] != grant.account_ref:
        raise EvidenceContractError("scope_mismatch")
    if not set(source["mail_refs"]).issubset(grant.mail_refs) or not set(value["evidence_refs"]).issubset(grant.evidence_refs):
        raise EvidenceContractError("reference_forbidden")
    _timestamp(value["observed_at"])
    coverage = value["coverage"]
    since, until = _timestamp(coverage["since"]), _timestamp(coverage["until"])
    if since is not None and until is not None and since > until:
        raise EvidenceContractError("coverage_window_invalid")
    if value["change"] == "upsert":
        if not source["mail_refs"]:
            raise EvidenceContractError("mail_reference_required")
        # A Pack may deliberately send a reference-only upsert.  Its mail and
        # evidence references remain bound to the grant, while every copied
        # metadata field (including subject and sender) is absent.
        if value["metadata"] is not None:
            _timestamp(value["metadata"]["date"])
        for key in ("tags", "axes"):
            _dimensions(value["semantics"][key])
    return value


def validate_observation_batch(payloads: object, *, grant: SourceGrant) -> list[dict[str, Any]]:
    if not isinstance(payloads, list) or len(payloads) > MAX_BATCH_SIZE:
        raise EvidenceContractError("batch_limit")
    _grant(grant)
    return [validate_observation(p, grant=grant) for p in payloads]


def validate_feedback(payload: object, *, grant: SourceGrant, actor_ref: str,
                      allowed_kinds: Collection[str]) -> dict[str, Any]:
    _grant(grant)
    value = _validate(payload, "feedback")
    if value["scope_id"] != grant.scope_id:
        raise EvidenceContractError("scope_mismatch")
    if not actor_ref or value["actor_ref"] != actor_ref:
        raise EvidenceContractError("actor_mismatch")
    if value["kind"] not in allowed_kinds:
        raise EvidenceContractError("feedback_forbidden")
    if not set(value["evidence_refs"]).issubset(grant.evidence_refs):
        raise EvidenceContractError("reference_forbidden")
    if value["kind"] == "execution_receipt":
        _timestamp(value["decision"]["occurred_at"])
    if "proposed_tags" in value["decision"]:
        _dimensions(value["decision"]["proposed_tags"])
    return value


def build_observation(*, grant: SourceGrant, observation_id: str, event_id: str,
                      case_ref: str, source_revision: int, observed_at: str,
                      mail_refs: list[str], thread_key: str | None, subject: str | None,
                      sender: str | None, date: str | None, raw_excerpt: str | None,
                      semantics: dict[str, Any], evidence_refs: list[str], coverage: dict[str, Any],
                      excerpt_policy: Callable[[str], str] | None = None,
                      semantic_pack: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a bounded observation from explicit evidence and a Pack output policy.

    The Pack selects generic output operations from its own axis/value labels;
    the engine never owns a business sensitivity taxonomy.  Without a declared
    matching policy the builder emits a reference-only upsert and does not invoke
    ``excerpt_policy`` or copy metadata.  Any operation that exposes text still
    requires the caller's approved original-text sanitizer.
    """
    _grant(grant)
    action = observation_excerpt_action(semantic_pack, semantics)
    mode = action["mode"]
    metadata: dict[str, Any] | None = None
    if mode != "reference_only":
        # A reference-only projection must be constructible without fetching or
        # inspecting source text/metadata.  Only text-exposing modes require it.
        if not all(isinstance(x, str) for x in (subject, sender, raw_excerpt)):
            raise EvidenceContractError("metadata_invalid")
        if excerpt_policy is None:
            raise EvidenceContractError("excerpt_policy_required")
        try:
            excerpt = excerpt_policy(raw_excerpt)
        except Exception:
            raise EvidenceContractError("excerpt_policy_rejected") from None
        if not isinstance(excerpt, str):
            raise EvidenceContractError("excerpt_policy_rejected")
        if mode == "truncate_excerpt":
            limit = action["max_chars"]
            excerpt = excerpt[:limit]
        elif mode == "omit_excerpt":
            excerpt = ""
        metadata = {
            "subject": subject[:256],
            "sender": sender[:254],
            "date": date,
            "excerpt": excerpt[:512],
            "excerpt_truncated": (
                mode == "omit_excerpt"
                or len(raw_excerpt) > 512
                or len(excerpt) > 512
                or (mode == "truncate_excerpt" and len(raw_excerpt) > action["max_chars"])
            ),
        }
    payload = {
        "schema_version": "1.0", "observation_id": observation_id, "event_id": event_id,
        "case_ref": case_ref, "source_revision": source_revision, "observed_at": observed_at,
        "source": {"system": "twinbox", "scope_id": grant.scope_id, "account_ref": grant.account_ref,
                   "mail_refs": mail_refs, "thread_key": thread_key},
        "change": "upsert", "metadata": metadata,
        "semantics": semantics, "evidence_refs": evidence_refs, "coverage": coverage,
    }
    return validate_observation(payload, grant=grant)
