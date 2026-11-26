# InsightScope-VLA

An edge-first audit tool that watches a short video, reads (or hears) what someone said
they did, and reports where the two disagree — with the exact frames that prove it.

Built for a desk, not a data centre: a phone clip, a local model via Ollama, and a SQLite
file. No cloud calls required.

```text
1. transcript ──► text model ──► claims ──► subjects to verify
                                                 │
2. clip.mp4 ──► OpenCV keyframes ────────────────┼──► vision model ──► observations
                 motion · anchors · snapping     │
                                                 ▼
3. claims + observations ──► deterministic rules ──► findings
                                                 │
4. findings ──► report writer ──► critic ──► report + flagged frames + audit log
```

Claims come first because open-ended discovery means the camera is asked specific
questions ("is the laptop closed?") rather than asked to describe everything.

## The one rule

> Models produce **observations**. Only deterministic code produces **decisions**.

Models never decide whether something is a contradiction, and never decide whether to
retry. They extract structured facts; Python compares them. This is what makes the output
auditable, and it is why the same input produces the same findings.

## Status

Phase 1 is complete: the whole pipeline runs offline against fake clients, including
the critique loop, retry budgets, annotated frames, and the SQLite audit log.

| Phase | Contents | State |
| --- | --- | --- |
| 0 | Repo, packaging, CI, docs | done |
| 1 | Domain vocabulary, deterministic rules, full graph with fake models | done |
| 2 | OpenCV keyframes, faster-whisper, Ollama clients, cassettes | in progress |
| 3 | Gradio UI, nightly evals, releases | not started |

## Quick start

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed automatically.

```bash
make setup     # create .venv and install dependencies
make check     # lint, format check, types, tests — the same commands CI runs
```

## Try it

```bash
# What would the audit look at? Selects keyframes and shows why each was kept.
insightscope keyframes clip.mp4

# Show the same selection with transcript-aware "before/after" frames.
insightscope keyframes clip.mp4 --transcript transcript.json

# Draft a checklist, inspect it, then use it. The model proposes; you approve.
insightscope checklist new "close the laptop, mug on the tray, stow the pen" -o desk.yaml
insightscope audit clip.mp4 --transcript transcript.json --checklist desk.yaml

# Offline: scripted clients, or a recorded cassette of real model responses.
insightscope audit clip.mp4 --transcript transcript.json
insightscope audit clip.mp4 --transcript transcript.json --replay desk.cassette.json
```

Local models, via Ollama:

```bash
uv sync --extra llm --extra asr          # OpenAI-compatible client + speech-to-text
ollama pull llama3.2-vision
ollama pull llama3.1:8b

# No transcript? Transcribe the clip's audio, then audit.
insightscope audit clip.mp4 --client ollama
```

`--transcript` accepts a timestamped `.json` or a plain `.txt`. A `.txt` has no
timestamps, so alignment is reported as degraded rather than invented. `--record`
writes every model response to a cassette so a run can be replayed later.

## The demo task

"Pack the desk": unplug the charger → close the laptop → mug on the tray → stow the pen.

The audit reports things like *"you said you closed the laptop; frame kf_3a91c0 shows the
lid open at 00:12"*, or *"you opened the drawer but never mentioned it"*.

## What this does not do (yet)

- **Understand arbitrary properties.** Subjects are open-ended: whatever the transcript
  mentions becomes a subject to verify, and an optional YAML checklist adds expected
  objects and ordered steps. Attributes are a *closed* vocabulary — `presence`,
  `open_closed_state`, `location`, `count`, `step_completed`. A claim about anything
  outside that list is not extracted rather than guessed at.
- **Prove absence.** If no keyframe covers a moment, the finding says "insufficient
  evidence", never "you didn't do it".
- **Run without a model server unless you choose to.** `--client fake` and `--replay`
  exercise the whole pipeline offline; `--client ollama` needs a local server plus the
  `llm` extra. Transcription uses faster-whisper `small.en` by default — an edge
  compromise, not a production speech pipeline.

## Docs

- [`docs/architecture.md`](docs/architecture.md) — layers, state, and routing.
- [`docs/data-handling.md`](docs/data-handling.md) — where artifacts live and what never
  gets committed.
- [`docs/adr/`](docs/adr/) — decisions and why they were made.

## License

MIT. See [LICENSE](LICENSE).
