---
owner: domain core
sources:
  - packages/alpha-core/src/**
  - packages/alpha-core/pyproject.toml
verified: f09c218332089ad6
---

# alpha-core workspace

## Purpose

The bottom layer: frozen domain values (`Bar`, traces, outcomes), the typed error family, the
structural protocols, corporate-action types, the shared fee rate, atomic file publication
(`atomic.py`, for the packages above core) and the typed settings
(`AlphaSettings`, `ALPHA_*` environment variables). It imports nothing internal (import-linter
contract "alpha_core imports nothing internal") and every other package imports it, so a change
here reaches the whole repository.

## Read first

| Read | Section | When |
|---|---|---|
| [core invariants](../../docs/reference/invariants/core.md) | Package boundary | always |
| [core invariants](../../docs/reference/invariants/core.md) | Domain values | always |
| [core invariants](../../docs/reference/invariants/core.md) | Errors | always |
| [engineering rules](../../docs/reference/invariants/engineering.md) | Import layers | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Invalid data fails loud | always |
| [core invariants](../../docs/reference/invariants/core.md) | Corporate actions and membership | changing corporate-action or membership types |
| [core invariants](../../docs/reference/invariants/core.md) | Protocols | changing a protocol that other packages implement |
| [core invariants](../../docs/reference/invariants/core.md) | Atomic publication | changing atomic file publication |
| [core invariants](../../docs/reference/invariants/core.md) | Costs | changing cost types |
| [core invariants](../../docs/reference/invariants/core.md) | Settings | changing settings |
| [core invariants](../../docs/reference/invariants/core.md) | Source identity | changing what core binds into a run id |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Corporate actions: two clocks | changing corporate-action types |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Deterministic seeds and identity | changing settings or seeds |
| [engineering rules](../../docs/reference/invariants/engineering.md) | Hash-bound source bytes | any source edit (run ids fingerprint core bytes) |
| [what this part is for](../../docs/reference/project/components/command-line.md) | — | why it exists; before you keep, shelve or remove it |

## How to change it

- Code: `packages/alpha-core/src/alpha_core/` (`types.py`, `errors.py`, `protocols.py`, `config.py`,
  `corporate.py`, `costs.py`, `atomic.py`). The package has no tests of its own; they live in the root suite.
- Tests: `tests/unit/test_core_types.py`, `tests/unit/test_core_atomic.py`, `tests/unit/test_bar_invariants.py`,
  `tests/unit/test_corporate_actions.py`, `tests/unit/test_universe_store.py`,
  `tests/bias_guards/test_universe_survivorship.py`.
- Check: `uv run python scripts/gate.py check`. Because almost every test imports core, a change
  here maps to a large selection; run `uv run python scripts/gate.py check --all` for the fast tier.
- A new setting must never enter a run id or manifest if it is machine-local (see core invariants).

## Outputs

- A unit test for every new value rule or error, and a bias guard if a protocol's read semantics change.
- The owning document: `docs/reference/invariants/core.md`; update it and its `verified` commit
  when a rule changes.
