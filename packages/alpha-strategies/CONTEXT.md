---
owner: strategy layer
sources:
  - packages/alpha-strategies/src/**
  - packages/alpha-strategies/pyproject.toml
verified: 1da6fae1949fc119
---

# alpha-strategies workspace

## Purpose

Nautilus strategy classes and the pure decision functions behind them: trailing-window signals,
volatility-target sizing, plain all-in sizing, rule specs and the shared paper-safe lifecycle. It imports only
`alpha_core` and `alpha_patterns` (import-linter contract "alpha_strategies depends only on core
and patterns"); only `alpha_cli` composes it. A strategy decides on the close of a bar and fills at
the next open, never earlier.

## Read first

| Read | Section | When |
|---|---|---|
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Package boundary | always |
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Decide at close, fill at next open | always |
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Pure signals | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | always |
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Sizing | changing position sizing |
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Rule specs | changing a rule spec or its validation |
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Shared lifecycle | changing the shared strategy lifecycle |
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Replay and sandbox strategies | changing replay or sandbox strategies |
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Source identity | changing what strategies bind into a run id |
| [backtest invariants](../../docs/reference/invariants/backtest.md) | Next-open fills | changing how orders are submitted |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | No live capital | changing paper or sandbox behaviour |
| [command line runs](../../docs/reference/invariants/cli-runs.md) | Run identity | adding a strategy module (it is fingerprinted) |
| [what this part is for](../../docs/reference/project/components/strategies-and-signals.md) | — | why it exists; before you keep, shelve or remove it |

## How to change it

- Code: `packages/alpha-strategies/src/alpha_strategies/` (`base.py`, `signals.py`, `sizing.py`,
  one module per strategy, `rule_strategy.py` for rule specs).
- Tests: `tests/unit/test_*strategy*.py`, `tests/unit/test_signals*.py`, `tests/unit/test_sizing*.py`,
  `tests/unit/test_rules_*.py`, `tests/unit/test_entry_gap_sizing.py`; bias guards `tests/bias_guards/test_momentum_signal_lookahead.py`,
  `test_signal_window_boundary.py`; integration `tests/integration/test_nautilus_engine.py`.
- A new strategy is registered in `apps/alpha-cli/src/alpha_cli/_strategies.py`; regenerate the
  command page if its options appear there (`uv run python scripts/commands_reference.py`).
- Check: `uv run python scripts/gate.py check`. Strategy source bytes are part of run identity, so
  any edit changes run ids of that strategy.

## Outputs

- Tests: a future-poison bias guard for every new signal; a unit test for every sizing rule.
- The owning document: `docs/reference/invariants/strategies.md`.
