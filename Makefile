.PHONY: setup check lint fmt type test clean

## One-time (or after dependency changes): create .venv and install everything.
setup:
	uv sync

## Everything CI runs. Run this before every push.
check: lint type test

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

type:
	uv run mypy

## Default test run: deterministic only, no model server needed.
test:
	uv run pytest -m "not live and not eval"

clean:
	rm -rf .venv .pytest_cache .ruff_cache .mypy_cache
