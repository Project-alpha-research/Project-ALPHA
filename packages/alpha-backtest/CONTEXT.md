---
owner: backtest engine
sources:
  - packages/alpha-backtest/src/**
  - packages/alpha-backtest/pyproject.toml
verified: 588f502d79a4857d
---

# alpha-backtest workspace

## Purpose

The NautilusTrader run harness: feed encoding, engine setup, fees and the result schema.
It imports only `alpha_core` and `alpha_data`. It must never let an order fill on the bar that triggered it.

## Read first

| Read | Section | When |
|---|---|---|
| [backtest invariants](../../docs/reference/invariants/backtest.md) | Package boundary | always |
| [backtest invariants](../../docs/reference/invariants/backtest.md) | Next-open fills | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Decide at close, fill at next open | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Immutable, hash-bound artefacts | always |
| [backtest invariants](../../docs/reference/invariants/backtest.md) | Fee and slippage model | changing fees, slippage or cost assumptions |
| [backtest invariants](../../docs/reference/invariants/backtest.md) | Accounts and rejections | changing accounts, order rejections or the Nautilus harness |
| [backtest invariants](../../docs/reference/invariants/backtest.md) | — | changing dividends, equity, replay or run-id binding |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Corporate actions: two clocks | changing dividend credits |
| [command line runs](../../docs/reference/invariants/cli-runs.md) | Artifacts and run directories | changing the result schema |
| [what this part is for](../../docs/reference/project/components/nautilus.md) | — | why it exists; before you keep, shelve or remove it |
| [backtest invariants](../../docs/reference/invariants/backtest.md) | Code map | finding a module or its tests |

## How to change it

- Code, tests and checks: [code map](../../docs/reference/invariants/backtest.md#code-map); run `uv run python scripts/gate.py check`.
- Engine source bytes are part of run identity: [source identity](../../docs/reference/invariants/backtest.md#source-identity).

## Outputs

- Tests: see the [code map](../../docs/reference/invariants/backtest.md#code-map).
- The owning document: `docs/reference/invariants/backtest.md`.
