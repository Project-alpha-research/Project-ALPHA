---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/*.py
verified: 0c8b05351952
---

# Benchmark and drawdowns

**Reach for it when** the question is "is it just the market?", a big drawdown arrives in a short period, or
the result works in some years only.

**Commands**

```text
uv run alpha diagnose <run_id> --json
uv run alpha results cite <run_id> benchmark_sharpe
uv run alpha figures render <run_id> --figure equity_vs_passive --figure drawdown_episodes
```

**How to read it**

- `benchmark` is buy and hold of the same asset on the same bars, with no costs. `strategy_minus_benchmark`
  holds the recorded differences. A rule that does not beat holding the asset: say that first.
- `drawdowns.episodes` lists the five deepest falls: `start`, `trough`, `recovery`, `depth`,
  `benchmark_return` over the same dates and `share_explained` (how much of the fall the asset itself
  explains). A `null` there has a `reason`, such as "not recovered by the last bar".
- `by_year` gives strategy and benchmark return per calendar year, partial years included, and
  `strategy_positive_years`. Profit that sits in one or two years is a finding.
- Flags to expect: `below-benchmark`, `drawdown-with-market`.

**What it cannot tell you**

- Why the market fell. `macro_window` reports stored macro series for the worst drawdown only when context
  data exists; otherwise `available: false`. Do not name a market event you have not checked against dates.
- Comparison with a sector, an index or Bitcoin, or a beta: the benchmark is the same asset only. Market
  states and regime detection are not available yet, so "it only works in some regimes" stays a hypothesis.

**Next** Run the same rule on a second, different asset with the [rule test](rule-test.md): if both fall on
the same dates, the market explanation gains weight.
