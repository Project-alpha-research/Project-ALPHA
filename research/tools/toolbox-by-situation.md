---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/situations.py
  - apps/alpha-cli/src/alpha_cli/toolbox/find.py
  - apps/alpha-cli/src/alpha_cli/toolbox/families/*.py
verified: a1934950ce3233d7
---

# Toolbox checks, by situation

Start from your situation, in plain words: `alpha tool find "<words>"` ranks the checks that fit.
`alpha tool situations` prints the list below, generated from the registry; a test keeps it equal.
A check gives a reading in context, never a pass or fail. Any check may run at any time, also on one part of an idea.

Choose checks before you see results when you can: `alpha tool declare <run_id> --set <name>`.
The result is then marked `declared`, otherwise `exploratory`. Nothing is refused. `alpha tool results <run_id>` shows the counts.
<!-- situations:begin -->
- The result looks too good: `performance.lo_sharpe`, `robustness.start_end_dates`, `trades.concentration`, `context.published_factors`,
  `resampling.sharpe_interval`, `resampling.drawdown_distribution`, `overfit.deflated_sharpe`
- The result looks too good after many tries: `overfit.deflated_sharpe`
- Big drawdown, or how deep the drop could get: `performance.ulcer`, `performance.pain`, `performance.sterling_burke`, `performance.worst_windows`,
  `performance.recovery_factor`, `performance.downside_ratios`, `resampling.drawdown_distribution`, `resampling.block_bootstrap_paths`,
  `resampling.student_t_paths`
- How wide is the return range: `performance.worst_windows`, `resampling.sharpe_interval`, `resampling.return_interval`, `resampling.block_bootstrap_paths`,
  `resampling.student_t_paths`
- Works in some years or windows only: `market.vol_regimes`, `market.changepoints`, `robustness.start_end_dates`
- Does it earn in calm or turbulent markets: `market.vol_regimes`
- When did the behaviour change: `market.changepoints`
- Few trades: `trades.concentration`, `resampling.sharpe_interval`, `resampling.return_interval`, `trades.dependence`
- Profit from a handful of trades: `trades.concentration`
- Wins and losses cluster or alternate: `performance.streaks`, `trades.dependence`
- Which side earned the profit: `trades.side_contribution`
- Fragile to costs: `performance.holding_period`, `costs.break_even`, `cost_realism.cost_sweep`, `cost_realism.churn_budget`, `cost_realism.financing_cost`,
  `cost_realism.after_tax`, `cost_realism.spread_estimates`, `cost_realism.gap_stress`, `cost_realism.market_impact`, `cost_realism.capacity_curve`,
  `cost_realism.commission_schedule`, `cost_realism.share_rounding`, `cost_realism.volume_share`, `cost_realism.limit_fill`
- Is this just the market going up: `market.attribution`, `costs.break_even`, `context.published_factors`
- Return compared with the risk taken: `performance.ulcer`, `performance.pain`, `performance.sterling_burke`, `performance.gain_to_pain`, `performance.kappa`,
  `performance.lo_sharpe`, `performance.cornish_fisher_sharpe`, `performance.payoff_expectancy`, `performance.downside_ratios`
- Does it hold up out of sample: No toolbox check yet. `alpha test` reports the out-of-sample numbers.
- Would a slightly different data feed change the answer: No toolbox check yet. `alpha data health <ASSET>` reports the data's faults.
- Is this just a known published factor: `context.published_factors`
<!-- situations:end -->

Rule: [toolbox rules](../../docs/reference/invariants/cli-toolbox.md#finding-checks-and-recording-the-plan).
