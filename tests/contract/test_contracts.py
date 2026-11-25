"""Wire contracts must reject anything we did not ask for."""

import pytest
from pydantic import ValidationError

from insightscope.contracts.extraction import ClaimBatch, ClaimItem, KeyframeAnalysis
from insightscope.contracts.report import Critique, Issue, ReportDraft
from insightscope.domain.ontology import Attribute


def test_claim_coerces_value_and_keeps_quote() -> None:
    claim = ClaimItem(
        subject="the coffee mug",
        attribute=Attribute.PRESENCE,
        value="yes",
        quote="the mug is on the tray",
    )
    assert claim.value is True


def test_claim_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ClaimItem(
            subject="mug",
            attribute=Attribute.PRESENCE,
            value=True,
            quote="mug",
            severity="blocker",  # type: ignore[call-arg]
        )


def test_claim_requires_the_quote_it_came_from() -> None:
    with pytest.raises(ValidationError):
        ClaimItem(subject="mug", attribute=Attribute.PRESENCE, value=True, quote="   ")


def test_claim_batch_defaults_to_empty() -> None:
    assert ClaimBatch().claims == []


def test_keyframe_analysis_allows_no_interaction() -> None:
    analysis = KeyframeAnalysis(keyframe_id="kf_0001")
    assert analysis.interacted_object is None
    assert analysis.verified == []


def test_vision_visibility_is_restricted() -> None:
    with pytest.raises(ValidationError, match="visibility"):
        KeyframeAnalysis.model_validate(
            {
                "keyframe_id": "kf_0001",
                "verified": [
                    {
                        "subject": "laptop",
                        "attribute": "open_closed_state",
                        "value": "open",
                        "visibility": "probably",
                    }
                ],
            }
        )


def test_critique_cannot_name_an_arbitrary_graph_node() -> None:
    with pytest.raises(ValidationError):
        Issue(
            code="unsupported_claim",
            severity="blocker",
            target="delete_everything",  # type: ignore[arg-type]
            ref="f_123",
            message="bad",
        )


def test_critique_requires_references() -> None:
    with pytest.raises(ValidationError):
        Issue(code="unclear", severity="minor", target="synthesize", ref="", message="hmm")


def test_critique_accept_needs_no_issues() -> None:
    assert Critique(verdict="accept").issues == []


def test_report_draft_requires_markdown() -> None:
    with pytest.raises(ValidationError):
        ReportDraft(markdown="", cited_finding_ids=[])
