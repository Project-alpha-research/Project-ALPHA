---
owner: literature worker
sources:
  - workers/literature/src/**
  - workers/literature/pyproject.toml
  - workers/literature/uv.lock
---

# Literature worker workspace

## Purpose

An isolated process that discovers, fetches and extracts research literature and returns bounded, validated claims.
Its output is advisory evidence, never research authority. No root package imports it.

## Read first

| Read | Section | When |
|---|---|---|
| [worker invariants](../../docs/reference/invariants/workers.md) | Shared rules | always |
| [worker invariants](../../docs/reference/invariants/workers.md) | Literature worker | always |
| [command line research](../../docs/reference/invariants/cli-research.md) | Process boundaries | changing how the CLI starts the worker |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Owner authority | changing what a claim can be used for |
| [what this part is for](../../docs/reference/project/components/literature-worker.md) | — | why it exists; before you keep, shelve or remove it |
| [worker invariants](../../docs/reference/invariants/workers.md) | Code map | finding a module or its tests |

## How to change it

- Code, tests and checks: [code map](../../docs/reference/invariants/workers.md#code-map); run `uv run python scripts/gate.py component literature` at the root.

## Outputs

- Tests in `workers/literature/tests/`.
- The owning document: `docs/reference/invariants/workers.md` § Literature worker.
