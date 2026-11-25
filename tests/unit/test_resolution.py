"""Binding 'this' to an object, or refusing to."""

from tests.support import claim, proposal

from insightscope.domain.aliases import UNSPECIFIED_TARGET, AliasTable
from insightscope.domain.ontology import Attribute
from insightscope.reconcile.resolution import resolve_claims

ALIASES = AliasTable.from_groups({"coffee_mug": ["cup", "mug"], "laptop": ["macbook"]})


def pronoun_claim(start: float = 10.0):
    return claim(UNSPECIFIED_TARGET, Attribute.OPEN_CLOSED, "closed", start=start)


def test_canonical_claims_pass_through_untouched() -> None:
    original = claim("laptop", Attribute.OPEN_CLOSED, "closed")
    outcome = resolve_claims(claims=[original], proposals=[], aliases=ALIASES, tolerance_s=3.0)
    assert outcome.claims == (original,)
    assert outcome.records == ()
    assert outcome.unresolved == ()


def test_single_proposal_binds_and_rehashes() -> None:
    original = pronoun_claim()
    outcome = resolve_claims(
        claims=[original],
        proposals=[proposal("the cup")],
        aliases=ALIASES,
        tolerance_s=3.0,
    )

    assert len(outcome.claims) == 1
    bound = outcome.claims[0]
    assert bound.subject_id == "coffee_mug"
    assert bound.assertion_id != original.assertion_id
    assert outcome.records[0].resolved_subject_id == "coffee_mug"
    assert outcome.unresolved == ()


def test_no_proposal_leaves_the_claim_unresolved() -> None:
    original = pronoun_claim()
    outcome = resolve_claims(claims=[original], proposals=[], aliases=ALIASES, tolerance_s=3.0)
    assert outcome.claims[0].subject_id == UNSPECIFIED_TARGET
    assert outcome.unresolved == (original.assertion_id,)
    assert "no interacting object" in outcome.records[0].note


def test_conflicting_proposals_are_not_guessed_between() -> None:
    outcome = resolve_claims(
        claims=[pronoun_claim()],
        proposals=[proposal("the cup"), proposal("laptop")],
        aliases=ALIASES,
        tolerance_s=3.0,
    )
    assert outcome.claims[0].subject_id == UNSPECIFIED_TARGET
    assert "ambiguous" in outcome.records[0].note
    assert "coffee_mug" in outcome.records[0].note


def test_proposals_outside_the_window_are_ignored() -> None:
    outcome = resolve_claims(
        claims=[pronoun_claim(start=10.0)],
        proposals=[proposal("the cup", start=30.0)],
        aliases=ALIASES,
        tolerance_s=3.0,
    )
    assert outcome.claims[0].subject_id == UNSPECIFIED_TARGET


def test_repeated_same_object_proposals_still_bind() -> None:
    outcome = resolve_claims(
        claims=[pronoun_claim()],
        proposals=[proposal("cup", start=9.5), proposal("the mug", start=10.5)],
        aliases=ALIASES,
        tolerance_s=3.0,
    )
    assert outcome.claims[0].subject_id == "coffee_mug"


def test_unknown_object_hint_becomes_its_own_subject() -> None:
    outcome = resolve_claims(
        claims=[pronoun_claim()],
        proposals=[proposal("monitor stand")],
        aliases=ALIASES,
        tolerance_s=3.0,
    )
    assert outcome.claims[0].subject_id == "monitor_stand"
