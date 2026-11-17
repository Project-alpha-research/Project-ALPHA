---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/*.py
verified: a5decc1fbca175a5
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
  `benchmark_return` over the same dates and `share_explained` (the asset's own fall divided by the rule's
  fall; 0.5 or more raises `drawdown-with-market`). A `null` there has a reason under `reasons`.
- `by_year` gives strategy and benchmark return per calendar year, partial years included, and
  `strategy_positive_years`. Profit that sits in one or two years is a finding.
- Flags to expect: `below-benchmark`, `drawdown-with-market`.

**What it cannot tell you**

- Why the market fell. `macro_window` reports stored macro series for the worst drawdown only when context
  data exists; otherwise `available: false`. Do not name a market event you have not checked against dates.
- Comparison with a sector, an index or Bitcoin, or a beta: the benchmark here is the same asset only; use
  [attribution and regimes](attribution-regimes-changepoints.md), whose regime models are fitted in sample.

**Next** Run the same rule on a second, different asset with the [rule test](rule-test.md): if both fall on
the same dates, the market explanation gains weight.
