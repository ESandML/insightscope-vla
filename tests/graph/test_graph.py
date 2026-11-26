"""Full graph runs against fake clients: happy path, retries, degradation, actions.

No network, no model server, no GPU. These tests are what Phase 1 promised: the whole
pipeline, wired exactly as production will be, with only the two clients swapped.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from insightscope.actions.db import history
from insightscope.clients.fake import FakeTextClient, FakeVisionClient, draft_citing_all
from insightscope.config import LoopConfig, RunConfig
from insightscope.contracts.extraction import ClaimItem, KeyframeAnalysis, VerifiedClaim
from insightscope.contracts.report import Critique, Issue, ReportDraft
from insightscope.domain.checklist import ChecklistSpec, StepSpec
from insightscope.domain.models import EvidenceManifest, KeyframeRef, TimeSpan, Utterance
from insightscope.domain.ontology import Attribute
from insightscope.graph.build import build_graph

GOLDEN = Path(__file__).parent.parent / "fixtures" / "reports" / "audit_report.md"
UTTERANCE_TEXT = "I closed the laptop"


def evidence(tmp_path: Path, text: str = UTTERANCE_TEXT) -> EvidenceManifest:
    frame = tmp_path / "kf_0001.jpg"
    assert cv2.imwrite(str(frame), np.zeros((120, 160, 3), dtype=np.uint8))
    span = TimeSpan(t_start_s=10.0, t_end_s=11.0)
    return EvidenceManifest(
        bundle_id="desk",
        source_path="clip.mp4",
        duration_s=60.0,
        keyframes=(
            KeyframeRef(
                keyframe_id="kf_0001",
                uri=str(frame),
                sha256="sha-kf-0001",
                span=span,
                reason="motion",
                width=160,
                height=120,
            ),
        ),
        utterances=(Utterance(utterance_id="u_0001", text=text, span=span),),
        transcript_mode="json",
    )


def config(tmp_path: Path, **overrides: object) -> RunConfig:
    values: dict[str, object] = {
        "artifacts_dir": tmp_path / "artifacts",
        "db_path": tmp_path / "audits.db",
    }
    values.update(overrides)
    return RunConfig(**values)  # type: ignore[arg-type]


def text_client(
    *,
    drafts: list | None = None,
    critiques: list[Critique] | None = None,
    fail: dict[str, int] | None = None,
) -> FakeTextClient:
    return FakeTextClient(
        claims={
            UTTERANCE_TEXT: [
                ClaimItem(
                    subject="laptop",
                    attribute=Attribute.OPEN_CLOSED,
                    value="closed",
                    quote=UTTERANCE_TEXT,
                )
            ]
        },
        drafts=drafts,
        critiques=critiques,
        fail=fail,
    )


def vision_client(*, fail: dict[str, int] | None = None) -> FakeVisionClient:
    return FakeVisionClient(
        analyses={
            "kf_0001": KeyframeAnalysis(
                keyframe_id="kf_0001",
                verified=[
                    VerifiedClaim(
                        subject="laptop",
                        attribute=Attribute.OPEN_CLOSED,
                        value="open",
                        confidence=0.9,
                    )
                ],
            )
        },
        fail=fail,
    )


async def run(
    tmp_path: Path,
    *,
    text: FakeTextClient | None = None,
    vision: FakeVisionClient | None = None,
    run_config: RunConfig | None = None,
    run_id: str = "run-test",
    ev: EvidenceManifest | None = None,
) -> dict:
    graph = build_graph(
        text_client=text or text_client(),
        vision_client=vision or vision_client(),
    )
    return await graph.ainvoke(
        {
            "run_id": run_id,
            "config": run_config or config(tmp_path),
            "evidence": ev if ev is not None else evidence(tmp_path),
        }
    )


def revise(target: str = "synthesize", severity: str = "blocker") -> Critique:
    return Critique(
        verdict="revise",
        issues=[
            Issue(
                code="unclear",
                severity=severity,  # type: ignore[arg-type]
                target=target,  # type: ignore[arg-type]
                ref="report",
                message="cite the conflicting frame explicitly",
            )
        ],
    )


async def test_happy_path_completes_and_dispatches(tmp_path: Path) -> None:
    final = await run(tmp_path)

    assert final["status"] == "complete"
    report = final["report"]
    assert report is not None
    assert len(report.findings) == 1
    assert report.findings[0].discrepancy.rule_id == "R-STATE-001"
    assert "R-STATE-001" in report.markdown

    actions = final["actions"]
    assert actions is not None
    assert actions.run_logged is True
    assert len(actions.annotated) == 1
    assert Path(actions.annotated[0]).exists()

    assert final["trace"] == [
        "ingest",
        "extract_claims",
        "extract_observations",
        "reconcile",
        "synthesize",
        "validate",
        "critique",
        "complete",
        "dispatch_actions",
    ]


async def test_run_is_logged_once_even_when_rerun(tmp_path: Path) -> None:
    run_config = config(tmp_path)
    await run(tmp_path, run_config=run_config)
    await run(tmp_path, run_config=run_config)

    rows = history(run_config.db_path)
    assert len(rows) == 1
    assert rows[0]["n_findings"] == 1


async def test_critic_can_force_one_rewrite(tmp_path: Path) -> None:
    client = text_client(
        drafts=[draft_citing_all("first attempt"), draft_citing_all("second attempt")],
        critiques=[revise(), Critique(verdict="accept")],
    )

    final = await run(tmp_path, text=client)

    assert final["status"] == "complete"
    assert final["cycle"] == 1
    assert final["trace"].count("synthesize") == 2
    assert "repair_synthesis" in final["trace"]
    assert "second attempt" in final["report"].markdown


async def test_budget_exhaustion_degrades_instead_of_looping(tmp_path: Path) -> None:
    client = text_client(critiques=[revise()])
    run_config = config(tmp_path, loop=LoopConfig(max_repair_cycles=1))

    final = await run(tmp_path, text=client, run_config=run_config)

    assert final["status"] == "complete_with_caveats"
    assert final["cycle"] == 1
    assert final["report"].caveats
    assert "complete_with_caveats" in final["report"].markdown


async def test_critic_can_send_the_run_back_to_extraction(tmp_path: Path) -> None:
    client = text_client(critiques=[revise(target="extract"), Critique(verdict="accept")])

    final = await run(tmp_path, text=client)

    assert final["status"] == "complete"
    assert final["trace"].count("extract_claims") == 2
    assert "repair_extraction" in final["trace"]


async def test_unknown_citation_is_caught_before_the_critic(tmp_path: Path) -> None:
    bad = ReportDraft(markdown="draft with a made-up citation", cited_finding_ids=["f_nope"])
    client = text_client(drafts=[lambda request: bad, draft_citing_all()])

    final = await run(tmp_path, text=client)

    assert final["status"] == "complete"
    assert final["trace"].count("validate") == 2
    assert "repair_synthesis" in final["trace"]
    # The critic only ever saw the valid draft.
    assert client.calls.count("critique") == 1


async def test_client_failure_escalates_with_a_partial_report(tmp_path: Path) -> None:
    client = text_client(fail={"synthesize": 1})

    final = await run(tmp_path, text=client)

    assert final["status"] == "escalated"
    assert final["fatal"]
    assert final["report"] is not None
    assert "fatal error" in final["report"].markdown
    assert final["actions"].run_logged is True


async def test_vision_failure_escalates(tmp_path: Path) -> None:
    final = await run(tmp_path, vision=vision_client(fail={"analyse": 1}))
    assert final["status"] == "escalated"


async def test_extraction_drops_a_claim_that_quotes_nothing(tmp_path: Path) -> None:
    client = FakeTextClient(
        claims={
            UTTERANCE_TEXT: [
                ClaimItem(
                    subject="laptop",
                    attribute=Attribute.OPEN_CLOSED,
                    value="closed",
                    quote="I locked the door",  # never said in this recording
                )
            ]
        }
    )
    # Point the claim at a different utterance by changing the transcript text.
    final = await run(tmp_path, text=client)
    assert final["reconciliation"].claims == ()
    assert any(error.code == "quote_not_found" for error in final["errors"])


async def test_golden_report_matches_fixture(tmp_path: Path) -> None:
    final = await run(tmp_path, run_id="run-golden")
    expected = GOLDEN.read_text(encoding="utf-8")
    assert final["report"].markdown == expected


def silent_evidence(tmp_path: Path, spans: list[tuple[float, float]]) -> EvidenceManifest:
    """A clip with no speech at all: Process/Spec mode with the audio ignored."""
    keyframes = []
    for index, (start, end) in enumerate(spans):
        frame = tmp_path / f"kf_{index:04d}.jpg"
        assert cv2.imwrite(str(frame), np.zeros((120, 160, 3), dtype=np.uint8))
        keyframes.append(
            KeyframeRef(
                keyframe_id=f"kf_{index:04d}",
                uri=str(frame),
                sha256=f"sha-kf-{index:04d}",
                span=TimeSpan(t_start_s=start, t_end_s=end),
                reason="motion",
                width=160,
                height=120,
            )
        )
    return EvidenceManifest(
        bundle_id="coffee",
        source_path="coffee.mp4",
        duration_s=60.0,
        keyframes=tuple(keyframes),
        utterances=(),
        transcript_mode="none",
    )


async def test_spec_fills_targets_for_a_silent_clip(tmp_path: Path) -> None:
    spec = ChecklistSpec(
        name="make_coffee",
        expected_objects=["kettle", "mug"],
        steps=[StepSpec(step_id="fill_kettle")],
    )
    vision = FakeVisionClient()
    graph = build_graph(text_client=FakeTextClient(), vision_client=vision)

    await graph.ainvoke(
        {
            "run_id": "run-silent",
            "config": config(tmp_path, checklist=spec),
            "evidence": silent_evidence(tmp_path, [(1.0, 2.0)]),
        }
    )

    targets = vision.requests[0].targets
    assert ("kettle", Attribute.PRESENCE, None) in targets
    assert ("mug", Attribute.PRESENCE, None) in targets
    assert ("fill_kettle", Attribute.STEP_COMPLETED, None) in targets


async def test_silent_clip_can_violate_step_order_visually(tmp_path: Path) -> None:
    spec = ChecklistSpec(
        name="make_coffee",
        expected_objects=["kettle"],
        steps=[StepSpec(step_id="fill_kettle"), StepSpec(step_id="pour_water")],
    )
    vision = FakeVisionClient(
        analyses={
            "kf_0000": KeyframeAnalysis(
                keyframe_id="kf_0000",
                verified=[
                    {
                        "subject": "pour_water",
                        "attribute": "step_completed",
                        "value": True,
                        "confidence": 0.9,
                    }
                ],
            ),
            "kf_0001": KeyframeAnalysis(
                keyframe_id="kf_0001",
                verified=[
                    {
                        "subject": "fill_kettle",
                        "attribute": "step_completed",
                        "value": True,
                        "confidence": 0.9,
                    }
                ],
            ),
        }
    )

    final = await run(
        tmp_path,
        vision=vision,
        run_config=config(tmp_path, checklist=spec),
        run_id="run-silent-order",
        ev=silent_evidence(tmp_path, [(1.0, 2.0), (3.0, 4.0)]),
    )

    findings = final["report"].findings
    assert [finding.discrepancy.rule_id for finding in findings] == ["R-STEP-002"]
    assert findings[0].discrepancy.span_seen is not None
    assert findings[0].discrepancy.span_seen.t_start_s == 1.0
    assert findings[0].discrepancy.kind == "sequence_violation"
    assert final["report"].status == "complete"


ACTION_TEXT = "I stirred the coffee"


def action_text_client() -> FakeTextClient:
    return FakeTextClient(
        claims={
            ACTION_TEXT: [
                ClaimItem(
                    subject="coffee",
                    attribute=Attribute.ACTION_COMPLETED,
                    action="stir",
                    value=True,
                    quote=ACTION_TEXT,
                )
            ]
        }
    )


def action_vision_client() -> FakeVisionClient:
    return FakeVisionClient(
        analyses={
            "kf_0001": KeyframeAnalysis(
                keyframe_id="kf_0001",
                verified=[
                    VerifiedClaim(
                        subject="coffee",
                        attribute=Attribute.ACTION_COMPLETED,
                        action="stir",
                        value=False,
                        confidence=0.9,
                    )
                ],
            )
        }
    )


async def test_spoken_action_is_verified_without_a_spec(tmp_path: Path) -> None:
    vision = action_vision_client()
    final = await run(
        tmp_path,
        text=action_text_client(),
        vision=vision,
        ev=evidence(tmp_path, text=ACTION_TEXT),
    )

    rules = [finding.discrepancy.rule_id for finding in final["report"].findings]
    assert rules == ["R-ACT-001"]
    assert ("coffee", Attribute.ACTION_COMPLETED, "stir") in vision.requests[0].targets


async def test_spoken_action_is_verified_in_a_hybrid_run(tmp_path: Path) -> None:
    spec = ChecklistSpec(
        name="make_coffee",
        expected_objects=["kettle"],
        steps=[StepSpec(step_id="fill_kettle"), StepSpec(step_id="pour_water")],
    )
    final = await run(
        tmp_path,
        text=action_text_client(),
        vision=action_vision_client(),
        run_config=config(tmp_path, checklist=spec),
        ev=evidence(tmp_path, text=ACTION_TEXT),
    )

    rules = {finding.discrepancy.rule_id for finding in final["report"].findings}
    assert "R-ACT-001" in rules
    assert "R-STEP-003" in rules
    assert "### Process / Spec Compliance" in final["report"].markdown
    assert "### Speech / Transcript Verification" in final["report"].markdown
