---
owner: afml worker
sources:
  - workers/afml/src/**
  - workers/afml/examples/**
  - workers/afml/pyproject.toml
  - workers/afml/uv.lock
---

# AFML worker workspace

## Purpose

An isolated process that runs two independent implementations of methods from *Advances in Financial Machine Learning*.
A number leaves only when both libraries agree. It is a separate uv project; no ALPHA package imports it.

## Read first

| Read | Section | When |
|---|---|---|
| [worker invariants](../../docs/reference/invariants/workers.md) | Shared rules | always |
| [worker invariants](../../docs/reference/invariants/workers.md) | AFML worker | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | changing volatility, events, barriers or weights |
| [glue rules](../../docs/adr/0051-glue-rules-for-outside-projects.md) | Decision | adding a function or changing a pin |
| [what this part is for](../../docs/reference/project/components/afml-worker.md) | — | why it exists; before you keep, shelve or remove it |
| [worker invariants](../../docs/reference/invariants/workers.md) | Code map | finding a module or its tests |

## How to change it

- Code, tests and checks: [code map](../../docs/reference/invariants/workers.md#code-map); run `uv run python scripts/gate.py component afml` at the root.

## Outputs

- Tests in `workers/afml/tests/`; Parquet and a JSON summary from `alpha-afml-worker`.
- The owning document: `docs/reference/invariants/workers.md` § AFML worker.
