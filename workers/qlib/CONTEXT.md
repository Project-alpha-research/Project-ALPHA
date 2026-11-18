---
owner: qlib worker
sources:
  - workers/qlib/src/**
  - workers/qlib/pyproject.toml
  - workers/qlib/uv.lock
verified: 7b9d7514e67f585b
---

# Qlib worker workspace

## Purpose

An isolated process that runs the real `pyqlib` package for daily cross-sectional model training.
Its results are advisory: ALPHA's own replay is the authority. No root package imports it.

## Read first

| Read | Section | When |
|---|---|---|
| [worker invariants](../../docs/reference/invariants/workers.md) | Shared rules | always |
| [worker invariants](../../docs/reference/invariants/workers.md) | Qlib worker | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Models and isolated workers | always |
| [command line machine learning](../../docs/reference/invariants/cli-ml.md) | Exchange contract | changing what the worker reads or writes |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | changing features or fold boundaries |
| [ADR-0042](../../docs/adr/0042-qlib-worker-delegates-data-layer-to-upstream.md) | Decision | changing a feature recipe or its normalisation |
| [what this part is for](../../docs/reference/project/components/qlib.md) | — | why it exists; before you keep, shelve or remove it |
| [worker invariants](../../docs/reference/invariants/workers.md) | Code map | finding a module or its tests |

## How to change it

- Code, tests and checks: [code map](../../docs/reference/invariants/workers.md#code-map); run `uv run python scripts/gate.py component qlib` at the root.

## Outputs

- Tests in `workers/qlib/tests/`; a root future-leakage test when exchange validation changes.
- The owning document: `docs/reference/invariants/workers.md` § Qlib worker.
