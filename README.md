# InsightScope-VLA

An edge-first audit tool that watches a short video, hears (or reads) what someone said
they did, and reports where the two disagree — with the exact frames that prove it.

Built for a kitchen counter, a workbench, or a lab bench: a phone clip, a local model via
Ollama, and a SQLite file. No cloud calls required.

## Four input modes

```text
speech source                              reference source
  1 listen      clip audio ──► faster-whisper        (none)
  2 transcript  .json / .txt                         (none)
  3 process     (audio ignored)   plain English ──► LLM ──► YAML spec
  4 spec        (audio ignored)                       YAML spec ──► loaded

                        claims + spec expectations
                                  │
clip.mp4 ──► OpenCV keyframes ──► vision model ──► observations
             motion · anchors · snapping
                                  │
                                  ▼
             deterministic rules ──► findings ──► report + critic
                                  │
                                  └──► flagged frames + audit log
```

Whisper runs in **mode 1 only**. Modes 2–4 never decode audio. A transcript may accompany
a spec, in which case its claims join the spec's expectations rather than replacing them.

An **audit spec** is a YAML file: expected objects, aliases, and ordered steps. A
**process description** is the plain-English version of the same thing; mode 3 asks a
model to convert it, writes the YAML to `artifacts/<run_id>/generated_spec.yaml`, and
runs against it — so you can inspect exactly what the model thought you meant.

## The one rule

> Models produce **observations**. Only deterministic code produces **decisions**.

Models never decide whether something is a contradiction, and never decide whether to
retry. They extract structured facts; Python compares them. This is what makes the output
auditable, and it is why the same input produces the same findings.

## Status

Phases 0–2 are complete. Slice A (unified input modes and visual process verification)
is in progress.

| Phase | Contents | State |
| --- | --- | --- |
| 0 | Repo, packaging, CI, docs | done |
| 1 | Domain vocabulary, deterministic rules, full graph with fake models | done |
| 2 | OpenCV keyframes, faster-whisper, Ollama clients, cassettes | done |
| 2.5 | Unified input modes, visual step verification, kitchen demo | in progress |
| 3 | Gradio UI, nightly evals, releases | not started |

## Quick start

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed automatically.

```bash
make setup     # create .venv and install dependencies
make check     # lint, format check, types, tests — the same commands CI runs
```

## Try it

```bash
# 1. Listen: transcribe the clip's audio, then audit open-ended claims.
insightscope audit clip.mp4 --client ollama

# 2. Transcript: skip speech-to-text entirely.
insightscope audit clip.mp4 --transcript transcript.json --client ollama

# 3. Process text: describe the intended steps; the generated spec is saved for review.
insightscope audit clip.mp4 \
  --process "fill the kettle, boil it, spoon coffee into the mug, pour, stir" \
  --client ollama

# 4. Spec: draft once, read it, then audit against it (with or without a transcript).
insightscope spec new "fill the kettle, boil, spoon coffee, pour, stir" -o coffee.yaml
insightscope audit clip.mp4 --spec coffee.yaml --client ollama
insightscope audit clip.mp4 --spec coffee.yaml --transcript transcript.json
```

`--checklist` still works as an alias for `--spec`, and `insightscope checklist new` as an
alias for `insightscope spec new`.

Offline, with no model server:

```bash
insightscope audit clip.mp4 --transcript transcript.json              # scripted clients
insightscope audit clip.mp4 --transcript transcript.json --replay run.cassette.json
```

Local models, via Ollama:

```bash
uv sync --extra llm --extra asr
ollama pull llama3.2-vision
ollama pull llama3.1:8b
```

`--transcript` accepts a timestamped `.json` or a plain `.txt`. A `.txt` has no
timestamps, so alignment is reported as degraded rather than invented. `--record`
writes every model response to a cassette so a run can be replayed later.

To see what the audit would look at, without running it:

```bash
insightscope keyframes clip.mp4 --transcript transcript.json
```

## Demo

> **Demo clip and Gradio walkthrough land in Slice B.**
>
> Planned: a 30-second kitchen clip — filling the kettle, spooning coffee, pouring water —
> opened in the browser. Drop the clip in, watch keyframes get selected with their reasons,
> see flagged frames appear where the narration and the video disagree, read the report,
> and browse the SQLite history.

The task it demonstrates is "make coffee": fill the kettle → boil → spoon coffee → pour
water → stir. The fixture lives at
[`tests/fixtures/checklists/make_coffee.yaml`](tests/fixtures/checklists/make_coffee.yaml).

The audit reports things like *"you said you poured the water; the frames show the kettle
still on its base at 00:18"*, or — when omissions are enabled — *"the mug was moved but
never mentioned"*.

## What this does not do (yet)

- **Understand arbitrary properties.** Subjects are open-ended: whatever the transcript
  mentions becomes a subject to verify, and an audit spec adds expected objects and
  ordered steps. Attributes are a *closed* vocabulary — `presence`,
  `open_closed_state`, `location`, `count`, `step_completed`. A claim about anything
  outside that list is not extracted rather than guessed at.
- **Prove absence.** If no keyframe covers a moment, the finding says "insufficient
  evidence", never "you didn't do it".
- **Run without a model server unless you choose to.** `--client fake` and `--replay`
  exercise the whole pipeline offline; `--client ollama` needs a local server plus the
  `llm` extra. Transcription uses faster-whisper `small.en` by default — an edge
  compromise, not a production speech pipeline.

## Docs

- [`docs/architecture.md`](docs/architecture.md) — layers, input modes, state, and routing.
- [`docs/data-handling.md`](docs/data-handling.md) — where artifacts live and what never
  gets committed.
- [`docs/adr/`](docs/adr/) — decisions and why they were made.

## License

MIT. See [LICENSE](LICENSE).
