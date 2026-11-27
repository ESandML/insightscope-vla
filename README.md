# InsightScope-VLA

**A general-purpose multimodal audit engine.** It compares what a camera actually saw
against what a person intended — spoken aloud, supplied as a transcript, written as a
plain-English process description, or declared in a YAML audit spec — and reports every
disagreement with the exact frames that prove it.

Edge-first by design: one phone clip, a local model via Ollama, and a SQLite file. No
cloud calls required, and every run can be replayed offline.

## What it does

```text
speech source                          reference source
  listen      clip audio ─► whisper      (none)           open-ended claims
  transcript  .json / .txt               (none)           open-ended claims
  audio       separate recording ─►      (none)           open-ended claims
  none        (audio ignored)            process ─► spec   process description
  none        (audio ignored)            spec              YAML audit spec

any speech source can pair with any reference:
  listen + process/spec · transcript + process/spec · audio + process/spec

                    claims + spec expectations
                              │
clip ─► OpenCV keyframes ─► vision model ─► observations
        motion · anchors · snapping
                              │
                              ▼
      deterministic rules ─► findings ─► report + critic
                              │
                              └─► annotated frames + SQLite history
```

Four base modes (**listen**, **transcript**, **process**, **spec**) plus `--audio` for a
separate voice recording, and six hybrids when speech and a reference are combined. A
spec run splits the report into *Process / Spec Compliance* and *Speech / Transcript
Verification*; open-ended runs keep one findings table.

`--process` and `--spec` default to **silent**. Whisper runs only when speech is `listen`
or `--audio`; transcript mode and the silent modes never decode audio.

Spoken actions are verified without a spec: *"I stirred the coffee"* becomes an
`action_completed` claim carrying the action `stir`, and `R-ACT-001` compares it with
aligned frames for that exact action. Listen and Transcript modes therefore check actions
the same way Spec mode checks steps.

## The neuro-symbolic split

> Models produce **observations**. Only deterministic code produces **decisions**.

LLMs and VLMs do perception and structured extraction: one keyframe becomes an
`Assertion`, one utterance becomes a claim. They never decide whether two facts conflict,
whether a step happened out of order, whether "this" has exactly one referent, or whether
a run should retry.

Python owns all of that: temporal alignment, pronoun resolution, step ordering, rule
evaluation, severity, adjudication, and every routing decision. The critic can force a
rewrite, never an assertion.

Three reasons this is the core design choice:

- **Reproducible.** The same clip and settings produce the same findings, because the
  deciding layer is a pure function of extracted facts.
- **Testable.** Rules are small functions with stable ids and table-driven tests. Model
  calls are contract-tested and recordable as cassettes.
- **Honest about absence.** When no frame covers a moment, the finding is
  `insufficient evidence`, not "it did not happen".

## Status

Phases 0–2 and both interface slices are complete. Phase 3 (evals and release tooling) is
in progress.

| Phase | Contents | State |
| --- | --- | --- |
| 0 | Repo, packaging, CI, docs | done |
| 1 | Domain vocabulary, deterministic rules, graph with fake models | done |
| 2 | OpenCV keyframes, faster-whisper, Ollama clients, cassettes | done |
| 2.5 | Unified input modes, visual step verification, kitchen demo | done |
| 3 | Gradio UI, nightly evals, release tooling | in progress |

## Quick start

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed automatically.

```bash
make setup     # create .venv and install everything, including the UI
make check     # lint, format, types, architecture contracts, tests — same as CI
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

# 4. Spec: draft once, inspect it, then audit against it.
insightscope spec new "put a tea bag in the mug, pour boiling water, brew, remove the bag, add milk" -o make_tea.yaml
insightscope audit clip.mp4 --spec make_tea.yaml --client ollama

# Hybrids: add speech (clip audio, transcript, or a separate recording) to a spec.
insightscope audit clip.mp4 --listen --spec make_tea.yaml --client ollama
insightscope audit clip.mp4 --transcript transcript.json --spec make_tea.yaml
insightscope audit silent.mp4 --audio voice.wav --spec make_tea.yaml --client ollama
```

Specs live in [`specs/`](specs/). `-o` and `--spec` accept a bare name (`make_tea` or
`make_tea.yaml`) and refuse anything that resolves outside that directory; pass
`--specs-dir DIR` to keep them somewhere else.

`--checklist` is an alias for `--spec`, and `insightscope checklist new` for
`insightscope spec new`.

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

### Flags that matter

| Flag | Meaning |
| --- | --- |
| `--transcript FILE` | Timestamped `.json` or plain `.txt`; never calls Whisper |
| `--listen` | Transcribe the clip's audio, including alongside `--process`/`--spec` |
| `--audio FILE` | Transcribe a separate recording (`.wav` / `.mp3` / `.m4a`) |
| `--process TEXT` / `--process-file FILE` | Generate an audit spec from plain English |
| `--spec FILE` / `--checklist FILE` | Load a YAML audit spec from `specs/` |
| `--specs-dir DIR` | Where specs live (default `specs/`, or `INSIGHTSCOPE_SPECS_DIR`) |
| `--client fake\|ollama` | Scripted offline clients (default), or a local server |
| `--text-model` / `--vision-model` / `--base-url` | Override the Ollama endpoints for a run |
| `--record FILE` / `--replay FILE` | Save or replay a cassette of model responses |
| `--whisper-model NAME` | faster-whisper size (default `small.en`) |
| `--artifacts-dir DIR` / `--db FILE` | Where run outputs and history live |
| `--max-keyframes` / `--analysis-fps` / `--motion-threshold` / `--max-side` | Keyframe selection tuning |
| `--flag-omissions` | Also report visible changes nobody mentioned (noisy) |

A `.txt` transcript has no timestamps, so alignment is reported as degraded rather than
invented. On a silent clip, listen mode fails fast and tells you to pass `--audio`,
`--transcript`, or a spec/process instead of leaving Whisper to fail obscurely.

To see what the audit would look at, without running it:

```bash
insightscope keyframes clip.mp4 --transcript transcript.json
```

## Demo

```bash
make ui              # dev install includes the UI
# runtime-only: uv sync --extra ui && uv run python app.py
```

Open <http://127.0.0.1:7860>.

1. **Drop in a kitchen clip.** If it has sound, **Listen to video audio** is enabled. If
   it is silent, the checkbox is disabled with a "No audio track detected" note and an
   external-audio dropzone appears (`.wav` / `.mp3` / `.m4a`).
2. **Edit the preloaded spec.** The *Audit spec (specs/)* dropdown lists `+ New spec` plus
   every saved YAML, and defaults to `make_tea.yaml`. Its YAML is loaded into the editor
   as soon as the page opens. Validation runs live: while the YAML is invalid, a status
   line under the editor explains why and **Save Spec** stays disabled. Save enables only
   when the text is valid *and* differs from the loaded file, then writes back to that
   same filename and preserves the `name:` you edited.
3. **Or generate a spec.** With an existing spec selected, **Generate Spec** regenerates
   the YAML from the process description into the editor for that file; the saved file is
   untouched until you press **Save Spec**. Choose **+ New spec** to start a second file:
   the editor clears, a **New spec filename** box appears, and Generate enables only when
   both a filename and a process description are present. Existing filenames are refused
   with an error instead of being overwritten. Uploaded `.yaml` files behave the same way
   and are selected in the dropdown.
4. **Pick a client.** The default is `ollama`, so a local server gives live generation and
   auditing. `fake` and `cassette replay` remain for offline runs — note that `fake`
   returns a scripted coffee fixture, and the status line says so if you generate a spec
   with it.
5. **Run Audit.** The status line tracks graph stages, then the tabs fill in: keyframes
   with their `reason` badges, annotated frames per finding, assertions as JSON, the
   Markdown report with separate Process/Spec and Speech tables, and past runs from
   `audits.db`. Edited YAML is saved before running, so the file on disk is what actually
   executed.

The UI calls the same `InputPlan` and pipeline as the CLI, so
`insightscope audit clip.mp4 --spec make_tea.yaml` produces the identical run directory.
One routing implementation, not two.

The demo task is "make tea": put the tea bag in the mug → add boiling water → brew →
remove the bag → add milk → stir → remove the spoon. It is chosen because the failure
modes are easy to spot and hard to fake:

- **Milk before water** — `R-STEP-002` flags the order violation from the frames.
- **Tea bag left in** — `R-STEP-003` reports the step as never mentioned and never seen.
- **"I stirred it" with no spoon movement** — `R-ACT-001` contradicts the spoken action
  without needing a spec.

`specs/make_coffee.yaml` is kept as a second example, and
`tests/fixtures/checklists/make_coffee.yaml` stays untouched for automated tests.

## Repository layout

```text
insightscope-vla/
├── app.py                      # Gradio entry point (make ui)
├── prompts/                    # versioned prompt templates, hashed for provenance
├── specs/                      # audit specs; make_tea.yaml is the demo
├── src/insightscope/
│   ├── cli.py                  # argument parsing only; routing lives in inputs/pipeline
│   ├── inputs.py               # InputPlan: speech source × reference source
│   ├── pipeline.py             # prepare_run / execute_run, shared by CLI and UI
│   ├── config.py               # frozen RunConfig + environment settings
│   ├── contracts/              # what models may return (Pydantic, extra="forbid")
│   ├── domain/                 # ontology, aliases, audit specs, assertions, findings
│   ├── telemetry/              # OpenCV keyframes, transcript loaders, whisper
│   ├── clients/                # protocols, fakes, Ollama, cassettes, prompt loader
│   ├── graph/                  # LangGraph state, nodes, pure routers
│   ├── reconcile/              # alignment, pronoun resolution, rules, adjudication
│   ├── actions/                # annotated frames and the SQLite audit log
│   ├── report/                 # deterministic Markdown rendering
│   └── ui/                     # Gradio app, service, audio state
├── tests/{unit,graph,contract,fixtures}
└── docs/{architecture.md,data-handling.md,adr/}
```

`reconcile/` may not import `clients/` or `graph/`; `domain/` may not import anything
above it. Both are enforced by import contracts in CI.

## What this does not do (yet)

- **Understand arbitrary properties.** Subjects are open-ended: whatever the transcript
  mentions becomes a subject to verify, and an audit spec adds expected objects and
  ordered steps. Attributes are a *closed* vocabulary — `presence`,
  `open_closed_state`, `location`, `count`, `action_completed`, `step_completed`. Actions
  that leave no static state ("stir", "wipe_counter") are checked through
  `action_completed` plus an explicit action name. A claim about anything outside that
  list is not extracted rather than guessed at.
- **Prove absence.** If no keyframe covers a moment, the finding says "insufficient
  evidence", never "you didn't do it".
- **Run model-backed audits without a local server.** `--client fake` and `--replay`
  exercise the whole pipeline offline; `--client ollama` needs a local server and the
  `llm` extra. Transcription uses faster-whisper `small.en` by default — an edge
  compromise, not a production speech pipeline.

## Docs

- [`docs/architecture.md`](docs/architecture.md) — layers, input modes, graph, state, rules.
- [`docs/data-handling.md`](docs/data-handling.md) — where artifacts live and what never
  gets committed.
- [`docs/adr/0001-deterministic-reconciliation.md`](docs/adr/0001-deterministic-reconciliation.md)
  — why conflict detection is code, not a prompt.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — branches, commits, and how to add a rule.

## License

MIT. See [LICENSE](LICENSE).
