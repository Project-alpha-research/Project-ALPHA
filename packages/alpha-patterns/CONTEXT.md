---
owner: pattern geometry
sources:
  - packages/alpha-patterns/src/**
  - packages/alpha-patterns/pyproject.toml
---

# alpha-patterns workspace

## Purpose

Pure chart-pattern geometry and causal indicators over OHLCV bars.
A pattern is reported only once it was knowable from the bars seen so far.

## Read first

| Read | Section | When |
|---|---|---|
| [pattern invariants](../../docs/reference/invariants/patterns.md) | Package boundary | always |
| [pattern invariants](../../docs/reference/invariants/patterns.md) | Knowable-at timing | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | always |
| [pattern invariants](../../docs/reference/invariants/patterns.md) | — | changing inputs, indicators, lookalikes, ports or controls |
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Rule specs | a strategy rule reads the changed indicator |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Statistical evidence | porting or changing a statistic |
| [what this part is for](../../docs/reference/project/components/strategies-and-signals.md) | — | why it exists; before you keep, shelve or remove it |
| [pattern invariants](../../docs/reference/invariants/patterns.md) | Code map | finding a module or its tests |

## How to change it

- Code, tests and checks: [code map](../../docs/reference/invariants/patterns.md#code-map); run `uv run python scripts/gate.py check`.

## Outputs

- Tests: see the [code map](../../docs/reference/invariants/patterns.md#code-map).
- The owning document: `docs/reference/invariants/patterns.md`.
