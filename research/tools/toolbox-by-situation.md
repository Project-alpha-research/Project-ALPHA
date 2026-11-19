---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/situations.py
  - apps/alpha-cli/src/alpha_cli/toolbox/find.py
  - apps/alpha-cli/src/alpha_cli/toolbox/families/*.py
verified: 4a75e93c3d780150
---

# Toolbox checks, by situation

Start from your situation, in plain words: `alpha tool find "<words>"` ranks the checks that fit.
`alpha tool situations` prints the list below, generated from the registry; a test keeps it equal.
A check gives a reading in context, never a pass or fail. Any check may run at any time, also on one part of an idea.

Choose checks before you see results when you can: `alpha tool declare <run_id> --set <name>`.
The result is then marked `declared`. Otherwise it is marked `exploratory`. Nothing is refused.
`alpha tool results <run_id>` shows the counts.
<!-- situations:begin -->
- The result looks too good: `robustness.start_end_dates`, `trades.concentration`, `resampling.sharpe_interval`, `resampling.drawdown_distribution`,
  `overfit.deflated_sharpe`
- The result looks too good after many tries: `overfit.deflated_sharpe`
- Big drawdown, or how deep the drop could get: `performance.downside_ratios`, `resampling.drawdown_distribution`, `resampling.block_bootstrap_paths`,
  `resampling.student_t_paths`
- How wide is the return range: `resampling.sharpe_interval`, `resampling.return_interval`, `resampling.block_bootstrap_paths`, `resampling.student_t_paths`
- Works in some years or windows only: `market.vol_regimes`, `market.changepoints`, `robustness.start_end_dates`
- Does it earn in calm or turbulent markets: `market.vol_regimes`
- When did the behaviour change: `market.changepoints`
- Few trades: `trades.concentration`, `resampling.sharpe_interval`, `resampling.return_interval`, `trades.dependence`
- Profit from a handful of trades: `trades.concentration`
- Wins and losses cluster or alternate: `trades.dependence`
- Which side earned the profit: `trades.side_contribution`
- Fragile to costs: `costs.break_even`
- Is this just the market going up: `market.attribution`, `costs.break_even`
- Return compared with the risk taken: `performance.downside_ratios`
- Does it hold up out of sample: none yet; see the other cards
- Would a slightly different data feed change the answer: none yet; see the other cards
<!-- situations:end -->

Rule: [toolbox rules](../../docs/reference/invariants/cli-toolbox.md#finding-checks-and-recording-the-plan).
