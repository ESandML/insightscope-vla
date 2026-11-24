# InsightScope-VLA

An edge-first audit tool that watches a short video, reads (or hears) what someone said
they did, and reports where the two disagree — with the exact frames that prove it.

Built for a desk, not a data centre: a phone clip, a local model via Ollama, and a SQLite
file. No cloud calls required.

```text
clip.mp4 ──► keyframes ──► vision model ──► assertions ─┐
                                                         ├─► deterministic rules ──► report
transcript ──► text model ──► assertions ───────────────┘         │
                                                                  └─► flagged frames + audit log
```

## The one rule

> Models produce **observations**. Only deterministic code produces **decisions**.

Models never decide whether something is a contradiction, and never decide whether to
retry. They extract structured facts; Python compares them. This is what makes the output
auditable, and it is why the same input produces the same findings.

## Status

Phase 0: repository scaffolding. Nothing below the docs is implemented yet.

| Phase | Contents | State |
| --- | --- | --- |
| 0 | Repo, packaging, CI, docs | in progress |
| 1 | Domain vocabulary, deterministic rules, full graph with fake models | not started |
| 2 | OpenCV keyframes, faster-whisper, Ollama clients, cassettes | not started |
| 3 | Gradio UI, nightly evals, releases | not started |

## Quick start

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed automatically.

```bash
make setup     # create .venv and install dependencies
make check     # lint, format check, types, tests — the same commands CI runs
```

## The demo task

"Pack the desk": unplug the charger → close the laptop → mug on the tray → stow the pen.

The audit reports things like *"you said you closed the laptop; frame kf_3a91c0 shows the
lid open at 00:12"*, or *"you opened the drawer but never mentioned it"*.

## What this does not do (yet)

- Understand arbitrary language. The vocabulary is a small closed list of desk-object
  attributes plus a step catalog; anything else is reported as unmapped rather than guessed.
- Prove absence. If no keyframe covers a moment, the finding says "insufficient evidence",
  never "you didn't do it".
- Run without a local model server for real video. Phase 1 runs entirely on fakes.

## Docs

- [`docs/architecture.md`](docs/architecture.md) — layers, state, and routing.
- [`docs/data-handling.md`](docs/data-handling.md) — where artifacts live and what never
  gets committed.
- [`docs/adr/`](docs/adr/) — decisions and why they were made.

## License

MIT. See [LICENSE](LICENSE).
