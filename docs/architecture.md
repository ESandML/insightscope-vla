# Architecture

## The rule everything follows

> Models produce observations. Deterministic code produces decisions.

Concretely: a vision or language model may only output structured facts (an `Assertion`),
and may only be asked to draft prose from facts that already exist. It never decides
whether two facts conflict, whether to retry, or whether the report is acceptable. Those
are Python, with tests.

Two consequences worth stating out loud:

1. **The critic can force a rewrite, never an assertion.** If the evidence cannot support a
   claim, the correct output is "not established" — not another sampling attempt.
2. **Routing is a pure function of state.** No model picks a graph edge.

## Layers

| Layer | Does | Deterministic | How it is tested |
| --- | --- | --- | --- |
| Evidence | Decode video, pick keyframes, load or transcribe speech | yes | hashes, frame counts, timestamps |
| Extraction | Keyframe → `Assertion`; utterance → `Assertion` | no | contract tests, cassettes |
| Reconciliation | Align saw/said, apply rules, adjudicate | yes | table-driven, one case per rule id |
| Synthesis | Findings → report draft | no | citation checks + LLM-as-judge |
| Verification | Validate, critique, route, repair | mixed | pure router tests, no graph needed |

`reconcile/` must not import `clients/` or `graph/`. `contracts/` must not import `graph/`.
This is enforced by an import-linter contract in CI, not by good intentions.

## Graph

```text
ingest ─► extract_observations (fan-out per keyframe) ─┐
       └► extract_claims       (fan-out per utterance) ┴─► align ─► reconcile ─► synthesize
                                                                                   │
                                                              validate ─► critique ─┤
                                                                                   ▼
                                                                              gate (pure)
                    ┌──────────────────────────┬─────────────────────────┬────────┘
                    ▼                          ▼                         ▼
                 finalize                   repair (targeted)        escalate
                    │                          │                         │
                    ▼                          └─► back to extract / synthesize
              dispatch_actions
                    │
                    ▼
                   END
```

`dispatch_actions` is terminal on purpose: a failed file write must never look like a
critic finding and re-enter the retry loop.

## State

One `TypedDict` (`graph/state.py`) is the only channel between nodes.

- **No media in state.** State holds references (`uri`, `sha256`, time span), never image
  bytes. LangGraph serialises state to the checkpointer on every step; base64 frames would
  mean multi-gigabyte checkpoints.
- **Append-only ledgers** for anything a fan-out writes (`Annotated[list[X], operator.add]`).
- **Budgets in config, attempts in a ledger.** Router helpers count occurrences rather than
  storing counters, so there is one source of truth and a free audit trail.
- **Derived facts are not stored.** `has_conflict` is a function of `discrepancies`, never a
  field that can drift.

## Evidence and absence

Keyframe selection is motion-based, which is blind to objects that never move. A mug that
sits still for the whole clip would otherwise generate a false "said but never seen"
finding.

Two mechanisms prevent that:

- **Baseline anchors** — always keep t=0 and one frame every `anchor_every_s`, regardless
  of motion.
- **Coverage** — the evidence manifest records which time spans keyframes actually cover.
  A rule that would say "never seen" checks coverage first and emits `insufficient_evidence`
  instead of `unsupported`.

## Verification loop

Gate order, highest priority first:

1. Hard validation failure (a quote that is not in the evidence, a citation that does not
   resolve) → deterministic repair. Do not spend model tokens on what code already proved.
2. Critic accepts → finalize.
3. Blocker issue, budget remaining → repair the target named by the issue.
4. Budget exhausted with blockers → degrade to `complete_with_caveats`, emit
   `insufficient_evidence` findings, finish.
5. Fatal error → `failed`, partial report, error ledger.

## Timing

All spans are seconds from the run's start, taken from media timestamps
(`CAP_PROP_POS_MSEC`, whisper segment times), never from frame index divided by nominal
FPS — phone clips are frequently variable frame rate.

Alignment defaults to ±3 s. Rules may override the window asymmetrically, because people
usually narrate an action a few seconds after doing it.
