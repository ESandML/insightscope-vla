"""Time-window pairing between claims and observations."""

from tests.support import claim, observation

from insightscope.domain.ontology import Attribute
from insightscope.reconcile.align import align_claims

WINDOW = (3.0, 3.0)


def test_pairs_same_subject_and_attribute() -> None:
    rows = align_claims(
        claims=[claim("laptop", Attribute.OPEN_CLOSED, "closed", start=10.0)],
        observations=[observation("laptop", Attribute.OPEN_CLOSED, "closed", start=10.0)],
        window=WINDOW,
    )
    assert len(rows) == 1
    assert rows[0].matched is True
    assert rows[0].delta_s == 0.0


def test_does_not_pair_different_subjects_or_attributes() -> None:
    assert not align_claims(
        claims=[claim("laptop", Attribute.OPEN_CLOSED, "closed")],
        observations=[observation("mug", Attribute.OPEN_CLOSED, "closed")],
        window=WINDOW,
    )
    assert not align_claims(
        claims=[claim("laptop", Attribute.OPEN_CLOSED, "closed")],
        observations=[observation("laptop", Attribute.PRESENCE, True)],
        window=WINDOW,
    )


def test_window_boundary_is_inclusive() -> None:
    # claim ends at 11.0; observation starts at 14.0, a gap of exactly 3.0 s.
    rows = align_claims(
        claims=[claim("laptop", Attribute.PRESENCE, True)],
        observations=[observation("laptop", Attribute.PRESENCE, True, start=14.0)],
        window=WINDOW,
    )
    assert len(rows) == 1


def test_outside_window_is_dropped() -> None:
    rows = align_claims(
        claims=[claim("laptop", Attribute.PRESENCE, True)],
        observations=[observation("laptop", Attribute.PRESENCE, True, start=14.5)],
        window=WINDOW,
    )
    assert rows == ()


def test_asymmetric_window_treats_narration_as_trailing() -> None:
    # People usually speak after acting, so allow 3 s after but only 1 s before.
    claims = [claim("laptop", Attribute.PRESENCE, True, start=10.0)]
    before = observation("laptop", Attribute.PRESENCE, True, start=7.5)
    after = observation("laptop", Attribute.PRESENCE, True, start=12.5)

    assert not align_claims(claims=claims, observations=[before], window=(1.0, 3.0))
    assert align_claims(claims=claims, observations=[after], window=(1.0, 3.0))


def test_every_candidate_is_recorded_and_the_closest_is_marked() -> None:
    rows = align_claims(
        claims=[claim("laptop", Attribute.PRESENCE, True, start=10.0)],
        observations=[
            observation("laptop", Attribute.PRESENCE, True, start=8.0, evidence=("kf_a",)),
            observation("laptop", Attribute.PRESENCE, True, start=10.2, evidence=("kf_b",)),
        ],
        window=WINDOW,
    )
    assert len(rows) == 2
    assert sum(row.matched for row in rows) == 1
    assert rows[0].delta_s is not None
    assert abs(rows[0].delta_s) < abs(rows[1].delta_s)  # type: ignore[arg-type]


def test_unspecified_claims_are_not_aligned() -> None:
    rows = align_claims(
        claims=[claim("unspecified_target", Attribute.PRESENCE, True)],
        observations=[observation("laptop", Attribute.PRESENCE, True)],
        window=WINDOW,
    )
    assert rows == ()
