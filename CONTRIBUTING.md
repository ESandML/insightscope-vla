# Contributing

## Setup

```bash
make setup
make check
```

`make check` must pass before you open a pull request. It runs the same commands as CI:
`ruff check`, `ruff format --check`, `mypy`, and the deterministic test suite.

## Branches

Trunk-based. `main` is protected and linear; everything lands by pull request.

```text
feat/short-description      new capability
fix/short-description       bug fix
docs/short-description      docs only
test/short-description      tests only
```

Keep branches short-lived. Squash-merge, so each PR becomes exactly one commit on `main`
and the history stays readable.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/), one logical change per commit.

```text
feat(reconcile): add step-order rule R-STEP-002
fix(keyframes): use POS_MSEC instead of frame_index / fps
test(graph): cover repair budget exhaustion
docs(adr): record why routing is deterministic
chore(deps): bump langgraph to 1.2
```

Scope is the package or area: `graph`, `reconcile`, `telemetry`, `clients`, `actions`, `ui`,
`docs`, `deps`, `ci`.

## What must pass

- `make check` green.
- New deterministic behaviour has a test. New rule ids get a row in the rule table test.
- No network in the default test suite. Anything needing a model server is marked
  `@pytest.mark.live` and skipped by default.
- No media, model weights, `.env` files, or run artifacts in the commit. Check
  `git status` before pushing; `.gitignore` covers the usual cases.

## Adding a rule

Rules live in `src/insightscope/reconcile/rules/`. Each one:

1. has a stable id (for example `R-OMIT-001`),
2. reads only assertions and coverage — never calls a model,
3. returns zero or more `Discrepancy` objects,
4. has a row in the table-driven rule test.

If a rule needs a model to work, it is not a rule.
