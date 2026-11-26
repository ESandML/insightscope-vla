# InsightScope-VLA

An edge-first audit tool that watches a short video, hears (or reads) what someone said
they did, and reports where the two disagree — with the exact frames that prove it.

Built for a kitchen counter, a workbench, or a lab bench: a phone clip, a local model via
Ollama, and a SQLite file. No cloud calls required.

## Input modes

Speech and reference are independent decisions:

```text
speech source                          reference source        mode
  listen      clip audio ──► whisper          (none)           1. listen
  transcript  .json / .txt                    (none)           2. transcript
  none        (audio ignored)                 process ─► spec  3. process text
  none        (audio ignored)                 spec             4. spec

hybrids, when speech is chosen explicitly with --listen or --transcript:
  listen      clip audio ──► whisper          process / spec   audio + process|spec
  transcript  .json / .txt                    process / spec   transcript + process|spec

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

`--process` and `--spec` default to **silent**: they ignore the audio unless you add
`--listen`. Whisper therefore runs when speech is `listen`, which by default means "no
spec reference" — and with `--listen` it runs alongside a spec too.

Spec runs split the report into `### Process / Spec Compliance` (step rules) and
`### Speech / Transcript Verification` (everything else), so a missing step and a wrong
claim never share a table. Open-ended runs keep one table.

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
| 2.5 | Unified input modes, visual step verification, kitchen demo | done |
| 3 | Gradio UI, nightly evals, releases | in progress |

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

# Hybrids: transcribe the audio *and* check it against a spec.
insightscope audit clip.mp4 --listen --spec coffee.yaml --client ollama
insightscope audit clip.mp4 --listen --process "fill the kettle, pour water" --client ollama
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

```bash
uv sync              # dev install includes the UI dependency
make ui              # or: uv sync --extra ui && uv run python app.py
```

Open <http://127.0.0.1:7860>.

1. **Drop in a kitchen clip.** If it has sound, **Listen to video audio** is enabled. If
   it is silent, the checkbox is disabled with a "No audio track detected" note and an
   external-audio dropzone appears (`.wav` / `.mp3` / `.m4a`).
2. **Describe the process** — "fill the kettle, boil it, spoon coffee into the mug, pour,
   stir" — and press **Generate Spec**. The YAML lands in the *Assertions & Spec* tab,
   where you can edit it before running. You can also drop in
   [`tests/fixtures/checklists/make_coffee.yaml`](tests/fixtures/checklists/make_coffee.yaml)
   directly.
3. **Pick a client.** `fake` for an offline walkthrough, `cassette replay` to replay a
   recorded run, `ollama` for real inference. Toggle omissions if you want
   "moved but never mentioned" findings.
4. **Run Audit.** The status line tracks graph stages, then the tabs fill in: keyframes
   with their `reason` badges, annotated frames per finding, assertions and the spec as
   JSON/YAML, the Markdown report with separate Process/Spec and Speech tables, and past
   runs from `audits.db`.

The UI builds the same `InputPlan` and calls the same pipeline as the CLI, so
`insightscope audit clip.mp4 --spec make_coffee.yaml` produces the identical run
directory. That is deliberate: there is one routing implementation, not two.

The task it demonstrates is "make coffee": fill the kettle → boil → spoon coffee → pour
water → stir.

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
