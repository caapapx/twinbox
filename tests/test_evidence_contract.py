"""013 boundary contract: all data here is synthetic, with no transport side effects."""
import copy
import json
from pathlib import Path

import pytest

from twinbox_core.evidence_contract import (
    EvidenceContractError, SourceGrant, build_observation, validate_feedback,
    validate_observation, validate_observation_batch,
)

CONTRACTS = Path(__file__).resolve().parents[1] / "specs/013-semantic-policy-projections/contracts"


def example(kind="observation"):
    return json.loads((CONTRACTS / f"{kind}.example.json").read_text())


@pytest.fixture
def grant():
    return SourceGrant(scope_id="example-scope-a", account_ref="example-account-a",
                       mail_refs=frozenset({"example-mail-001"}),
                       evidence_refs=frozenset({"example-mail-001:excerpt-1"}), enabled=True)


def test_canonical_example_and_unknown_business_values(grant):
    payload = example()
    payload["semantics"]["tags"]["future_dimension"] = ["future_value"]
    output = validate_observation(payload, grant=grant)
    assert output == payload
    output["metadata"]["subject"] = "changed"
    assert output != payload


@pytest.mark.parametrize("path,value", [
    (("body",), "private body"), (("metadata", "body"), "private body"),
    (("semantics", "tags", "project"), [{"body": "private"}]),
    (("semantics", "tags", "acl"), ["admin"]),
    (("semantics", "axes", "permissions"), "all"),
    (("semantics", "tags", "body_text"), ["private"]),
    (("source", "scope_id"), "another-scope"),
    (("source", "account_ref"), "another-account"),
    (("source", "mail_refs"), ["not-authorized"]),
    (("evidence_refs",), ["not-authorized"]),
    (("schema_version",), "2.0"), (("metadata", "excerpt"), "长" * 513),
    (("source_revision",), True), (("source_revision",), 1.0),
    (("observed_at",), "2026-09-18"), (("observed_at",), "not-a-date"),
    (("coverage", "since"), "2027-01-01T00:00:00Z"),
    (("semantics", "axes", "risk"), float("nan")),
])
def test_reject_bad_observation_without_echoing_payload(grant, path, value):
    payload = example()
    current = payload
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    with pytest.raises(EvidenceContractError) as exc:
        validate_observation(payload, grant=grant)
    assert "private" not in str(exc.value)
    assert len(str(exc.value)) < 100


def test_total_utf8_and_batch_limits(grant):
    payload = example()
    payload["semantics"]["tags"] = {f"dimension{i}": ["合" * 96] * 8 for i in range(16)}
    with pytest.raises(EvidenceContractError, match="payload_too_large"):
        validate_observation(payload, grant=grant)
    with pytest.raises(EvidenceContractError, match="batch_limit"):
        validate_observation_batch([example()] * 101, grant=grant)
    assert len(validate_observation_batch([example()] * 100, grant=grant)) == 100


def test_disabled_grant_is_fail_closed():
    with pytest.raises(EvidenceContractError, match="source_disabled"):
        validate_observation(example(), grant=SourceGrant(scope_id="example-scope-a", account_ref="example-account-a"))


def test_tombstone_cannot_keep_old_excerpt(grant):
    payload = example()
    payload["change"] = "tombstone"
    with pytest.raises(EvidenceContractError):
        validate_observation(payload, grant=grant)
    payload.update(metadata=None, semantics=None, evidence_refs=[])
    assert validate_observation(payload, grant=grant)["metadata"] is None


def _outbound_kwargs(grant):
    payload = example()
    identity = {k: payload[k] for k in ("observation_id", "event_id", "case_ref", "source_revision", "observed_at")}
    return dict(**identity, grant=grant, mail_refs=payload["source"]["mail_refs"],
                thread_key=payload["source"]["thread_key"], subject="S" * 300, sender="sender@example.invalid",
                date=payload["metadata"]["date"], raw_excerpt="secret " + "原" * 600,
                semantics=payload["semantics"], evidence_refs=payload["evidence_refs"], coverage=payload["coverage"])


def _policy_pack():
    from twinbox_core.pack import validate_pack
    return validate_pack({
        "id": "synthetic-output-policy",
        "classification": {"event_types": []},
        "output_policy": {
            "excerpt": {
                "default": {"mode": "reference_only"},
                "axes": {
                    # This is intentionally not the business word "sensitivity".  The engine
                    # must act on Pack-declared axes, rather than own an enterprise taxonomy.
                    "sharing_band": {
                        "open": {"mode": "allow"},
                        "brief": {"mode": "truncate_excerpt", "max_chars": 3},
                        "masked": {"mode": "omit_excerpt"},
                        "sealed": {"mode": "reference_only"},
                    },
                },
            },
        },
    })


def test_outbound_builder_is_reference_only_without_a_declared_pack_policy(grant):
    kwargs = _outbound_kwargs(grant)
    # The default path must not need source text or copied mail metadata at all.
    kwargs.update(subject=None, sender=None, raw_excerpt=None,
                  excerpt_policy=lambda _: pytest.fail("raw text must not be processed"))
    result = build_observation(**kwargs)
    assert result["metadata"] is None
    assert result["source"]["mail_refs"] == ["example-mail-001"]
    assert result["evidence_refs"] == ["example-mail-001:excerpt-1"]


def test_outbound_builder_applies_pack_declared_excerpt_projection_modes(grant):
    base = _outbound_kwargs(grant)
    pack = _policy_pack()

    def build(band, **extra):
        kwargs = copy.deepcopy(base)
        kwargs.update(extra)
        kwargs["semantics"]["axes"] = {"sharing_band": band}
        return build_observation(**kwargs, semantic_pack=pack)

    open_result = build("open", excerpt_policy=lambda text: text.replace("secret", "[redacted]"))
    assert len(open_result["metadata"]["subject"]) == 256
    assert len(open_result["metadata"]["excerpt"]) <= 512
    assert open_result["metadata"]["excerpt_truncated"] is True
    assert "secret" not in open_result["metadata"]["excerpt"]

    brief_result = build("brief", raw_excerpt="abcdef", excerpt_policy=lambda text: text)
    assert brief_result["metadata"]["excerpt"] == "abc"
    assert brief_result["metadata"]["excerpt_truncated"] is True

    masked_result = build("masked", raw_excerpt="not for the platform", excerpt_policy=lambda text: text)
    assert masked_result["metadata"]["excerpt"] == ""
    assert masked_result["metadata"]["excerpt_truncated"] is True

    sealed_result = build("sealed", excerpt_policy=lambda _: pytest.fail("raw text must not be processed"))
    assert sealed_result["metadata"] is None


def test_undeclared_pack_axis_value_fails_safe_to_reference_only(grant):
    kwargs = _outbound_kwargs(grant)
    kwargs["semantics"]["axes"] = {"sharing_band": "new-unreviewed-value"}
    result = build_observation(**kwargs, semantic_pack=_policy_pack(),
                               excerpt_policy=lambda _: pytest.fail("raw text must not be processed"))
    assert result["metadata"] is None


def test_feedback_grant_actor_and_kind(grant):
    payload = example("feedback")
    assert validate_feedback(payload, grant=grant, actor_ref="synthetic-reviewer", allowed_kinds={"correction_proposal"}) == payload
    for actor, kinds, code in [("different-actor", {"correction_proposal"}, "actor_mismatch"),
                                ("synthetic-reviewer", set(), "feedback_forbidden")]:
        with pytest.raises(EvidenceContractError, match=code):
            validate_feedback(payload, grant=grant, actor_ref=actor, allowed_kinds=kinds)
    payload["kind"] = "execution_receipt"
    with pytest.raises(EvidenceContractError):
        validate_feedback(payload, grant=grant, actor_ref="synthetic-reviewer", allowed_kinds={"execution_receipt"})


def test_tag_correction_preserves_dimension_names(grant):
    payload = example("feedback")
    payload["decision"] = {"field": "tags", "proposed_tags": {"project": ["synthetic-project-b"]}, "reason": "explicit evidence"}
    assert validate_feedback(payload, grant=grant, actor_ref="synthetic-reviewer", allowed_kinds={"correction_proposal"})["decision"]["proposed_tags"]["project"] == ["synthetic-project-b"]
    payload["decision"]["proposed_tags"]["grants"] = ["admin"]
    with pytest.raises(EvidenceContractError):
        validate_feedback(payload, grant=grant, actor_ref="synthetic-reviewer", allowed_kinds={"correction_proposal"})


def test_packaged_schemas_are_exact_snapshots():
    import twinbox_core.evidence_contract as contract
    for kind in ("observation", "feedback"):
        assert (Path(contract.__file__).parent / "schemas" / f"{kind}.schema.json").read_bytes() == (CONTRACTS / f"{kind}.schema.json").read_bytes()
