---
owner: pattern geometry
sources:
  - packages/alpha-patterns/src/**
  - packages/alpha-patterns/pyproject.toml
verified: 7852451a83024b77
---

# alpha-patterns workspace

## Purpose

Pure chart-pattern geometry and causal indicators over OHLCV bars: swing structure, trendlines,
wedges, head and shoulders, order blocks, fair-value gaps, harmonics and oscillators, plus shape
lookalikes and novelty through STUMPY (`lookalike.py`, the one module that imports it). It imports
only `alpha_core`, numpy and that one library (import-linter contract "alpha_patterns depends only on core");
`alpha_strategies`, `alpha_study` and `alpha_cli` import it. A pattern must only be reported once
it was knowable from the bars seen so far.

## Read first

| Read | Section | When |
|---|---|---|
| [pattern invariants](../../docs/reference/invariants/patterns.md) | Package boundary | always |
| [pattern invariants](../../docs/reference/invariants/patterns.md) | Knowable-at timing | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | always |
| [pattern invariants](../../docs/reference/invariants/patterns.md) | Input series | changing how a pattern or indicator reads its input series |
| [pattern invariants](../../docs/reference/invariants/patterns.md) | Causal indicators | adding or changing an indicator |
| [pattern invariants](../../docs/reference/invariants/patterns.md) | Lookalikes and novelty | changing lookalike or novelty searches |
| [pattern invariants](../../docs/reference/invariants/patterns.md) | Ports and provenance | porting outside code or changing its provenance |
| [pattern invariants](../../docs/reference/invariants/patterns.md) | Synthetic ground truth and controls | adding or changing synthetic controls |
| [strategy invariants](../../docs/reference/invariants/strategies.md) | Rule specs | a strategy rule reads the changed indicator |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Statistical evidence | porting or changing a statistic |
| [what this part is for](../../docs/reference/project/components/strategies-and-signals.md) | — | why it exists; before you keep, shelve or remove it |

## How to change it

- Code: `packages/alpha-patterns/src/alpha_patterns/` (one module per detector or indicator).
- Tests: one unit file per detector in `tests/unit/` (for example `test_wedge.py`, `test_harmonics.py`),
  `tests/unit/test_pattern_*.py`, `tests/unit/test_*_bias_guard.py`; bias guards
  `tests/bias_guards/test_hs_no_lookahead.py`, `test_pattern_no_lookahead.py`,
  `test_indicator_no_lookahead.py`, `test_oscillator_no_lookahead.py`, `test_lookalike_future_poison.py`
  (with `tests/unit/test_lookalike.py`).
- Parity tests pin other packages to this one: `tests/unit/test_rules_indicators_parity.py`
  (strategies read exactly what the chart draws) and `tests/oracles/test_differential_runs_test.py`.
- Check: `uv run python scripts/gate.py check`. This package is not in the quant tier.

## Outputs

- Tests: a no-look-ahead bias guard and a synthetic ground-truth case for every new detector.
- The owning document: `docs/reference/invariants/patterns.md`.
