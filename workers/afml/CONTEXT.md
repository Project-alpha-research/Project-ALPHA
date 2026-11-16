---
owner: afml worker
sources:
  - workers/afml/src/**
  - workers/afml/examples/**
  - workers/afml/pyproject.toml
  - workers/afml/uv.lock
verified: 16df47f3f9a310df
---

# AFML worker workspace

## Purpose

An isolated process that runs two independent implementations of methods from López de Prado's
*Advances in Financial Machine Learning*: RiskLabAI (primary) and quantowl (second opinion).
Today it offers sample uniqueness and weights, the sequential bootstrap, CUSUM events, triple-barrier
labels and meta-labels, purged CV, fractional differencing, feature importance and Sharpe statistics. A number leaves only when both libraries agree (or, for
labels on highs and lows, when ALPHA's own adapter code computed it). It is a separate uv
project with its own lock; no ALPHA package imports it and it imports no ALPHA package.
[ADR-0054](../../docs/adr/0054-afml-worker.md)

## Read first

| Read | Section | When |
|---|---|---|
| [worker invariants](../../docs/reference/invariants/workers.md) | Shared rules | always |
| [worker invariants](../../docs/reference/invariants/workers.md) | AFML worker | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | changing volatility, events, barriers or weights |
| [glue rules](../../docs/adr/0051-glue-rules-for-outside-projects.md) | Decision | adding a function or changing a pin |
| [what this part is for](../../docs/reference/project/components/afml-worker.md) | — | why it exists; before you keep, shelve or remove it |

## How to change it

- Code: `workers/afml/src/alpha_afml_worker/` (`contract.py` checks input; `uniqueness.py`,
  `labels.py`, `cv.py`, `fracdiff.py`, `importance.py`, `stats.py` are the adapter); tests: `workers/afml/tests/` (`shared_fixtures.py` holds the
  shared inputs: hand-built bars and a seeded synthetic series). Never commit market data.
- A new function gets a parity test first: a hand-worked value, and the two libraries equal to
  1e-10 where both implement it. A look-ahead-sensitive one also gets a truncation test.
- Read each library's API from the installed source in `workers/afml/.venv`, never from memory.
- From `workers/afml`: `uv lock --check`, `uv sync --locked`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run mypy`, `uv run pytest -q -m "not network"`.
- Or CI's job from the repository root: `uv run python scripts/gate.py component afml`.
- `alpha labels barrier|weights` calls this worker; its picture is `figure.py`. Real-data example:
  `uv run python examples/owner_figure.py --help` (writes outside git).

## Outputs

- Tests in `workers/afml/tests/`; Parquet and a JSON summary from `alpha-afml-worker`.
- The owning document: `docs/reference/invariants/workers.md` § AFML worker.
