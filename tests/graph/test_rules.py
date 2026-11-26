"""Table-driven rule tests through the whole reconciler.

Each row is a small world: what was said, what was seen, and exactly which findings
that should produce. Running through ``reconcile`` rather than calling rules directly
means alignment, coverage, gating, and adjudication are all exercised too — the table
fails if any of them drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from tests.support import change_event, claim, manifest, observation

from insightscope.config import RunConfig
from insightscope.domain.checklist import ChecklistSpec, StepSpec
from insightscope.domain.models import Assertion, ChangeEvent, EvidenceManifest
from insightscope.domain.ontology import Attribute
from insightscope.reconcile import reconcile
from insightscope.reconcile.rules import ALL_RULES

SINGLE_STEP = ChecklistSpec(name="single", steps=[StepSpec(step_id="fill_kettle")])
TWO_STEPS = ChecklistSpec(
    name="two",
    steps=[StepSpec(step_id="fill_kettle"), StepSpec(step_id="pour_water")],
)


@dataclass
class Case:
    name: str
    expected: set[tuple[str, str, str]]
    claims: list[Assertion] = field(default_factory=list)
    observations: list[Assertion] = field(default_factory=list)
    changes: list[ChangeEvent] = field(default_factory=list)
    checklist: ChecklistSpec | None = None
    flag_omissions: bool = False
    evidence: EvidenceManifest | None = None
    requested: tuple[str, ...] | None = None


CASES: list[Case] = [
    Case(
        name="presence agreed",
        claims=[claim("laptop", Attribute.PRESENCE, True)],
        observations=[observation("laptop", Attribute.PRESENCE, True)],
        expected=set(),
    ),
    Case(
        name="said present but every frame disagrees",
        claims=[claim("laptop", Attribute.PRESENCE, True)],
        observations=[observation("laptop", Attribute.PRESENCE, False)],
        expected={("R-PRES-001", "contradiction", "major")},
    ),
    Case(
        name="said gone but still in frame",
        claims=[claim("laptop", Attribute.PRESENCE, False)],
        observations=[observation("laptop", Attribute.PRESENCE, True)],
        expected={("R-PRES-002", "contradiction", "major")},
    ),
    Case(
        name="disagreeing frames are unclear, not a conflict",
        claims=[claim("laptop", Attribute.PRESENCE, True)],
        observations=[
            observation("laptop", Attribute.PRESENCE, True, start=10.0),
            observation("laptop", Attribute.PRESENCE, False, start=10.5),
        ],
        expected=set(),
    ),
    Case(
        name="open vs closed is major",
        claims=[claim("laptop", Attribute.OPEN_CLOSED, "closed")],
        observations=[observation("laptop", Attribute.OPEN_CLOSED, "open")],
        expected={("R-STATE-001", "contradiction", "major")},
    ),
    Case(
        name="ajar vs open is a minor nuance",
        claims=[claim("laptop", Attribute.OPEN_CLOSED, "ajar")],
        observations=[observation("laptop", Attribute.OPEN_CLOSED, "open")],
        expected={("R-STATE-001", "contradiction", "minor")},
    ),
    Case(
        name="count mismatch",
        claims=[claim("pen", Attribute.COUNT, 2)],
        observations=[observation("pen", Attribute.COUNT, 3)],
        expected={("R-COUNT-001", "value_mismatch", "major")},
    ),
    Case(
        name="location mismatch",
        claims=[claim("pen", Attribute.LOCATION, "on_desk")],
        observations=[observation("pen", Attribute.LOCATION, "in_drawer")],
        expected={("R-LOC-001", "value_mismatch", "minor")},
    ),
    Case(
        name="unobserved window is insufficient, never a contradiction",
        claims=[claim("laptop", Attribute.PRESENCE, True, start=100.0)],
        expected={("R-COVER-001", "insufficient_evidence", "info")},
    ),
    Case(
        name="observed window with no answer is insufficient",
        claims=[claim("lamp", Attribute.PRESENCE, True)],
        expected={("R-COVER-002", "insufficient_evidence", "info")},
    ),
    Case(
        name="pronoun with no proposal stays unresolved",
        claims=[claim("unspecified_target", Attribute.OPEN_CLOSED, "closed")],
        expected={
            ("R-REF-001", "unresolved_reference", "minor"),
            ("R-COVER-002", "insufficient_evidence", "info"),
        },
    ),
    Case(
        name="camera reported a subject nobody asked about",
        observations=[observation("cup", Attribute.PRESENCE, True)],
        requested=("laptop",),
        expected={("R-SUBJ-001", "subject_unmatched", "info")},
    ),
    Case(
        name="step rules are off without a spec",
        claims=[claim("fill_kettle", Attribute.STEP_COMPLETED, True)],
        expected=set(),
    ),
    Case(
        name="claimed step with no visual support",
        claims=[claim("fill_kettle", Attribute.STEP_COMPLETED, True)],
        checklist=SINGLE_STEP,
        expected={("R-STEP-001", "unsupported", "major")},
    ),
    Case(
        name="steps claimed out of catalog order",
        claims=[
            claim("pour_water", Attribute.STEP_COMPLETED, True, start=5.0),
            claim("fill_kettle", Attribute.STEP_COMPLETED, True, start=10.0),
        ],
        observations=[
            observation("pour_water", Attribute.STEP_COMPLETED, True, start=5.0),
            observation("fill_kettle", Attribute.STEP_COMPLETED, True, start=10.0),
        ],
        checklist=TWO_STEPS,
        expected={("R-STEP-002", "sequence_violation", "major")},
    ),
    Case(
        name="silent video shows steps out of order",
        observations=[
            observation("pour_water", Attribute.STEP_COMPLETED, True, start=5.0),
            observation("fill_kettle", Attribute.STEP_COMPLETED, True, start=10.0),
        ],
        checklist=TWO_STEPS,
        expected={("R-STEP-002", "sequence_violation", "major")},
    ),
    Case(
        name="spec step never mentioned and never seen",
        claims=[claim("fill_kettle", Attribute.STEP_COMPLETED, True)],
        observations=[observation("fill_kettle", Attribute.STEP_COMPLETED, True)],
        checklist=TWO_STEPS,
        expected={("R-STEP-003", "missing_step", "major")},
    ),
    Case(
        name="omissions stay quiet unless enabled",
        changes=[change_event("chair")],
        expected=set(),
    ),
    Case(
        name="omission enabled reports an unmentioned change",
        changes=[change_event("chair")],
        flag_omissions=True,
        expected={("R-OMIT-001", "omission", "info")},
    ),
    Case(
        name="omission ignores subjects that were mentioned",
        claims=[claim("mug", Attribute.PRESENCE, True)],
        observations=[observation("mug", Attribute.PRESENCE, True)],
        changes=[change_event("mug")],
        flag_omissions=True,
        expected=set(),
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_rule_table(case: Case) -> None:
    result = reconcile(
        claims=case.claims,
        observations=case.observations,
        changes=case.changes,
        evidence=case.evidence if case.evidence is not None else manifest(),
        config=RunConfig(checklist=case.checklist, flag_omissions=case.flag_omissions),
        requested_subjects=case.requested,
    )

    actual = {
        (finding.discrepancy.rule_id, finding.discrepancy.kind, finding.discrepancy.severity)
        for finding in result.findings
    }
    assert actual == case.expected


def test_every_rule_has_at_least_one_table_case() -> None:
    exercised = {rule_id for case in CASES for (rule_id, _, _) in case.expected}
    declared = {rule.rule_id for rule in ALL_RULES}
    assert exercised == declared, f"untested rules: {sorted(declared - exercised)}"
