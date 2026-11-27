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

## Input modes

| Mode | Flag | Speech | Reference |
| --- | --- | --- | --- |
| Listen (default) | none | faster-whisper | open-ended claims |
| Transcript | `--transcript FILE` | file (`.json` / `.txt`) | open-ended claims |
| External audio | `--audio FILE` | separate recording | open-ended claims |
| Process text | `--process` / `--process-file` | none (audio ignored) | LLM → YAML spec |
| Spec | `--spec` (alias `--checklist`) | none (audio ignored) | YAML spec loaded |
| Audio + process | `--listen --process` | faster-whisper | LLM → YAML spec |
| Audio + spec | `--listen --spec` | faster-whisper | YAML spec loaded |
| Transcript + process | `--transcript FILE --process` | file | LLM → YAML spec |
| Transcript + spec | `--transcript FILE --spec` | file | YAML spec loaded |
| External audio + process | `--audio FILE --process` | separate recording | LLM → YAML spec |
| External audio + spec | `--audio FILE --spec` | separate recording | YAML spec loaded |
Speech and reference are independent axes. `--listen`, `--transcript` and `--audio` are
mutually exclusive speech sources; `--process`/`--process-file`/`--spec` are mutually
exclusive references. `--process` and `--spec` default to silence; `--listen` or
`--audio` supplies speech anyway, which produces the six hybrid modes.

Whisper is gated in exactly one place, `pipeline.resolve_transcript`: it runs when the
speech source is `listen` or `audio`, which by default means "no spec reference". Hybrid
runs are reported as `hybrid (listen + spec make_tea)`, never as a single mode.

Listen mode probes the container first. `has_audio_stream` uses PyAV (a faster-whisper
dependency) and returns True when it cannot tell, so a silent clip fails with a clear
"pass --audio, --transcript, or a --spec/--process" message instead of an opaque
transcription error.

The Gradio UI does not re-implement any of this: it calls `plan_for` in
`insightscope.inputs` and runs `prepare_run`/`execute_run` from `insightscope.pipeline`,
the same functions the CLI uses.

A **process description** is plain English. An **audit spec** is the validated YAML
(`ChecklistSpec`). Generation is a separate, inspectable step: mode 3 writes the spec to
`specs/<name>.yaml` (the canonical copy) and `artifacts/<run_id>/generated_spec.yaml`
(the run's record), so a human approves the model's interpretation before it drives an
audit.

## Specs directory

All specs live in one place. `resolve_spec_path` accepts a bare name
(`make_tea` or `make_tea.yaml`), appends `.yaml` when needed, and confines the result to
`specs/`; `../`, absolute paths elsewhere, and symlinks out of the directory raise
`ChecklistError` instead of being read. `save_spec_to_dir` refuses filenames with
directory components, so a spec is always exactly one file in the directory.

Generated specs are written to `specs/<name>.yaml` as well as the run directory. The
Gradio UI lists `specs/` with a leading `+ New spec`, preloads the selected spec
(default `make_tea.yaml`) into an editor on the left, and validates YAML live. **Save
Spec** enables only when the text is valid and differs from the loaded file; new specs
require an explicit filename, and existing filenames are refused rather than overwritten.
**Generate Spec** works in both modes: with an existing spec it stages regenerated YAML in
the editor without writing, and for `+ New spec` it writes the new file. The UI defaults
to the `ollama` client for live runs. The fixture used by tests
(`tests/fixtures/checklists/make_coffee.yaml`) is deliberately separate and not part of
the user-facing store.

## Graph

```text
START
  │
  ▼
ingest ─► extract_claims ─► extract_observations ─► reconcile ─► synthesize ─► validate
                                                     (resolve · align · rules │
                                                      · adjudicate)           ▼
                                                                          critique
                                                                              │
                                                          gate (pure policy) ─┤
                            ┌──────────────────┬──────────────────────────────┤
                            ▼                  ▼                              ▼
                         finalize      repair_synthesis              repair_extraction
                            │                  │                              │
                            │                  └─► synthesize                └─► extract_claims
                            ├─► finalize_caveats ─┐
                            └─► escalate ─────────┴─► dispatch_actions ─► END
```

`reconcile` is a single node. Pronoun resolution, alignment, rule evaluation and
adjudication happen inside it; they are listed on the diagram because they are the
important steps, not because they are separate graph nodes.

Claims are extracted **before** vision runs, because the vision step needs a list of
subjects to verify. That costs parallelism and buys targeted questions ("is the kettle on
its base?") instead of "describe everything", which is both cheaper and easier to test.

In Process and Spec modes there may be no speech at all. The spec supplies the targets
instead: expected objects at `presence`, steps at `step_completed`. A silent clip still
gets a meaningful audit rather than an empty one.

Fan-out happens *inside* the two extraction nodes (`asyncio.gather` bounded by a
semaphore), not through LangGraph's `Send`. At 12 keyframes per-item checkpointing
buys nothing, and returning one sorted list removes merge-order nondeterminism. Revisit
if a run ever needs to resume halfway through a large keyframe set.

`dispatch_actions` is terminal on purpose: a failed file write must never look like a
critic finding and re-enter the retry loop.

## Subjects, specs, and expectations

Without a spec the pipeline audits whatever the transcript talks about. Three rules keep
that deterministic:

- **Subjects are open, attributes are closed.** `subject_id` is produced by code
  (lowercase, strip articles, apply aliases), so two spellings join only when an alias
  says they should. Unknown names are kept as their own subject, never fuzzy-matched.
  The closed attribute set is `presence`, `open_closed_state`, `location`, `count`,
  `action_completed`, `step_completed`.
- **Pronouns are deferred, not guessed.** "I closed this" becomes a claim with subject
  `unspecified_target`. The vision model may propose which object the speaker is
  touching; a pure Python step binds the claim only when exactly one candidate exists.
  Zero or several candidates produce an `unresolved_reference` finding.
- **Expectations are optional.** A spec enables the step rules (order, missing steps,
  completion). Without one those rules are skipped, not emulated.

Actions that leave no static state are first-class without a spec. A claim carries
`action_completed` plus a normalised action name ("stir", "wipe_counter"), and
`R-ACT-001` compares it with aligned observations for the same `(subject, action)`.
Alignment includes the action in its key, so a "fill" claim can never be checked against
a "pour" frame. Listen and Transcript modes therefore verify spoken actions the way Spec
mode verifies steps.

With a spec, two more things happen:

- **Vision targets come from the spec as well as the claims.** Expected objects are
  checked at `presence`, steps at `step_completed`. A silent Process/Spec run therefore
  still asks the camera concrete questions.
- **Step order can be verified visually.** `R-STEP-002` uses spoken claims when they
  exist; otherwise it orders the first `step_completed=True` observation per step by
  keyframe timestamp. A silent video that pours before filling is still a violation.

Omission detection (`seen but never mentioned`) is off by default: casual footage has
too much background motion, and a report full of "you moved a chair" is a report nobody
reads. Turn it on per run with `flag_omissions: true`.

## State

One `TypedDict` (`graph/state.py`) is the only channel between nodes.

- **No media in state.** State holds references (`uri`, `sha256`, time span), never image
  bytes. LangGraph serialises state to the checkpointer on every step; base64 frames would
  mean multi-gigabyte checkpoints.
- **Append-only ledgers** for anything a fan-out writes (`Annotated[list[X], operator.add]`).
- **Budgets in config, attempts in a ledger.** Router helpers count occurrences rather than
  storing counters, so there is one source of truth and a free audit trail.
- **Derived facts are not stored.** Whether a conflict exists is
  `bool(reconciliation.findings)`, not a separate flag that can drift.

## Evidence and absence

Keyframe selection is motion-based, which is blind to objects that never move. A kettle
that sits still for the whole clip would otherwise generate a false "said but never seen"
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

## Report layout

Findings answer two different questions, so a spec run keeps them apart:

- `### Process / Spec Compliance` — rules `R-STEP-*`: was every step done, in order, with
  visual support?
- `### Speech / Transcript Verification` — everything else, including `R-ACT-001`: does
  what was said match what was seen?

`render_markdown` splits when `has_spec` is set or when both families have findings, and
names an empty section explicitly ("No deviations from the spec.") rather than hiding it.
Pure open-ended runs keep the single `## Findings` table, which is why the golden report
fixture is stable.

## Timing

All spans are seconds from the run's start, taken from media timestamps
(`CAP_PROP_POS_MSEC`, whisper segment times), never from frame index divided by nominal
FPS — phone clips are frequently variable frame rate.

Alignment defaults to ±3 s. Rules may override the window asymmetrically, because people
usually narrate an action a few seconds after doing it.
