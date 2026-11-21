---
owner: strategy layer
sources:
  - packages/alpha-strategies/src/**
  - packages/alpha-strategies/pyproject.toml
verified: 052023176fd77aee
---

# alpha-strategies workspace

## Purpose

Nautilus strategy classes and the pure decision functions behind them: signals, sizing, rule specs and the shared lifecycle.
A strategy decides on a bar's close and fills at the next open, never earlier.

## Read first

| Read | Section | When |
|---|---|---|
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Package boundary | always |
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Decide at close, fill at next open | always |
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Pure signals | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | always |
| [strategy invariants](../../docs/reference/invariants/strategies.md) | — | changing sizing, rule specs, lifecycle or replay |
| [backtest invariants](../../docs/reference/invariants/backtest.md) | Next-open fills | changing how orders are submitted |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | No live capital | changing paper or sandbox behaviour |
| [command line runs](../../docs/reference/invariants/cli-runs.md) | Run identity | adding a strategy module (it is fingerprinted) |
| [what this part is for](../../docs/reference/project/components/strategies-and-signals.md) | — | why it exists; before you keep, shelve or remove it |
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Code map | finding a module or its tests |

## How to change it

- Code, tests and checks: [code map](../../docs/reference/invariants/strategies.md#code-map); run `uv run python scripts/gate.py check`.
- Strategy source bytes are part of run identity: [source identity](../../docs/reference/invariants/strategies.md#source-identity).

## Outputs

- Tests: see the [code map](../../docs/reference/invariants/strategies.md#code-map).
- The owning document: `docs/reference/invariants/strategies.md`.
