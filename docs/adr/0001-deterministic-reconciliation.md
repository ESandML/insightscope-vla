# ADR 0001 — Conflict detection is deterministic code, not a prompt

- Status: accepted
- Date: 2026-11-24

## Context

The obvious way to build this is a single prompt: give a vision-language model the frames,
give a language model the transcript, ask "do these agree?" It demos well and is wrong for
the job.

Three problems:

1. **No reproducibility.** The same clip produces different findings on different runs. An
   audit that cannot be re-run is not an audit.
2. **No test coverage for the part that matters.** You can test that a model call returns
   JSON. You cannot regression-test a judgement buried in prose instructions.
3. **No defensible absence.** A model asked "is the mug on the counter?" will usually
   answer yes or no. The honest answer, when no frame shows that moment, is "I cannot
   tell".

## Decision

Models are confined to two jobs: extraction (keyframe → structured `Assertion`,
utterance → structured `Assertion`) and drafting prose from findings that already exist.
They never decide whether facts conflict, whether a step is out of order, or whether a run
should retry. Both extraction outputs are constrained by Pydantic schemas; subjects are
open-ended but attributes come from a closed vocabulary, so comparisons stay exact.

All comparison happens in `reconcile/`, as named rules over normalised assertions:

- every rule has a stable id (`R-OMIT-001`),
- rules read assertions plus evidence coverage, never a model,
- each rule has a table-driven test,
- severity and confidence are derived from the rule, not from a model's self-report.

Routing between graph nodes is likewise a pure function of state (`graph/policy.py`).

## Consequences

Good:

- Deterministic, replayable findings; golden-file tests are possible.
- Conflict recall and precision are measurable against labelled fixtures.
- "Insufficient evidence" is a first-class outcome rather than a model's guess.
- New checks are small functions, reviewable in a diff.

Costs:

- The vocabulary must be extended deliberately. A new attribute is a schema change plus
  rules, not a sentence in a prompt.
- Extraction quality becomes the ceiling: if the model emits the wrong triple, rules reason
  correctly about the wrong fact. This is why extraction gets contract tests and cassettes.
- Two layers to debug instead of one. In exchange, you can tell which layer is at fault.

## Alternatives considered

- **One big prompt for vision + judgement.** Rejected: unreproducible, untestable.
- **LLM-as-judge decides conflicts.** Rejected as a *decider*. Kept as a *critic* of the
  drafted report, where being non-deterministic is acceptable because deterministic
  validators sit in front of it.
- **Free-text triples with fuzzy matching.** Rejected: fuzzy matching hides the ambiguity
  that an audit should surface. Unknown subjects are reported as unmatched, never silently
  merged into a neighbour.
