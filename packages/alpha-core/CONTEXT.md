---
owner: domain core
sources:
  - packages/alpha-core/src/**
  - packages/alpha-core/pyproject.toml
---

# alpha-core workspace

## Purpose

The bottom layer: frozen domain values, typed errors, protocols, corporate-action types, atomic publication and settings.
It imports nothing internal; every other package imports it, so a change reaches the whole repository.

## Read first

| Read | Section | When |
|---|---|---|
| [core invariants](../../docs/reference/invariants/core.md) | Package boundary | always |
| [core invariants](../../docs/reference/invariants/core.md) | Domain values | always |
| [core invariants](../../docs/reference/invariants/core.md) | Errors | always |
| [engineering rules](../../docs/reference/invariants/engineering.md) | Import layers | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Invalid data fails loud | always |
| [core invariants](../../docs/reference/invariants/core.md) | — | changing corporate actions, protocols, costs or settings |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Corporate actions: two clocks | changing corporate-action types |
| [engineering rules](../../docs/reference/invariants/engineering.md) | Hash-bound source bytes | any source edit (run ids fingerprint core bytes) |
| [what this part is for](../../docs/reference/project/components/command-line.md) | — | why it exists; before you keep, shelve or remove it |
| [core invariants](../../docs/reference/invariants/core.md) | Code map | finding a module or its tests |

## How to change it

- Code, tests and checks: [code map](../../docs/reference/invariants/core.md#code-map); run `uv run python scripts/gate.py check`.
- A machine-local setting never enters a run id: [settings](../../docs/reference/invariants/core.md#settings).

## Outputs

- Tests: see the [code map](../../docs/reference/invariants/core.md#code-map).
- The owning document: `docs/reference/invariants/core.md`; update it and its `verified` commit
  when a rule changes.
