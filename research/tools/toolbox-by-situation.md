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
- The result looks too good: `overfit_controls.min_backtest_length`, `overfit_controls.noise_best_sharpe`, `overfit_controls.required_history`,
  `overfit_controls.shrunk_sharpe`, `performance.lo_sharpe`, `overfit_controls.probabilistic_sharpe`, `overfit_controls.min_track_record`,
  `overfit_controls.haircut_sharpe`, `overfit_controls.deflated_at_tries`, `overfit_controls.t_stat_hurdle`, `overfit_controls.sequential_test`,
  `robustness.start_end_dates`, `trades.concentration`, `context.published_factors`, `resampling.sharpe_interval`, `resampling.drawdown_distribution`,
  `overfit.deflated_sharpe`, `resampling.wild_bootstrap`, `resampling.return_shuffle`, `resampling.phase_surrogates`, `resampling.interleaved_halves`
- The result looks too good after many tries: `overfit_controls.min_backtest_length`, `overfit_controls.noise_best_sharpe`, `overfit_controls.haircut_sharpe`,
  `overfit_controls.deflated_at_tries`, `overfit_controls.t_stat_hurdle`, `overfit.deflated_sharpe`
- Big drawdown, or how deep the drop could get: `risk.parametric_var`, `risk.cornish_fisher_var`, `risk.fractional_kelly`, `attribution.drawdown_causes`,
  `performance.ulcer`, `performance.pain`, `performance.sterling_burke`, `performance.worst_windows`, `performance.recovery_factor`,
  `performance.downside_ratios`, `risk.tail_fit`, `risk.var_coverage`, `risk.var_independence`, `resampling.drawdown_distribution`,
  `resampling.block_bootstrap_paths`, `resampling.student_t_paths`, `resampling.moving_block_paths`, `resampling.risk_of_ruin`, `resampling.phase_surrogates`,
  `resampling.trade_order_drawdown`, `resampling.calendar_year_shuffle`, `resampling.stress_shocks`
- How wide is the return range: `risk.parametric_var`, `risk.cornish_fisher_var`, `performance.worst_windows`, `risk.tail_fit`, `risk.var_coverage`,
  `resampling.sharpe_interval`, `resampling.return_interval`, `resampling.block_bootstrap_paths`, `resampling.student_t_paths`,
  `resampling.moving_block_paths`, `resampling.wild_bootstrap`
- Works in some years or windows only: `attribution.weekday`, `market.vol_regimes`, `market.changepoints`, `robustness.start_end_dates`,
  `resampling.calendar_year_shuffle`, `resampling.interleaved_halves`, `resampling.year_jackknife`
- Does it earn in calm or turbulent markets: `risk.vol_target`, `market.vol_regimes`
- When did the behaviour change: `market.changepoints`
- Few trades: `risk.kelly`, `risk.optimal_f`, `risk.loss_streaks`, `attribution.hold_period`, `attribution.weekday`, `overfit_controls.trade_count`,
  `overfit_controls.sequential_test`, `trades.concentration`, `resampling.sharpe_interval`, `resampling.return_interval`, `trades.dependence`,
  `resampling.wild_bootstrap`, `resampling.trade_order_drawdown`, `resampling.trade_jackknife`
- Profit from a handful of trades: `attribution.hold_period`, `trades.concentration`, `resampling.trade_jackknife`, `resampling.year_jackknife`
- Wins and losses cluster or alternate: `risk.loss_streaks`, `performance.streaks`, `risk.var_independence`, `trades.dependence`, `resampling.return_shuffle`
- Which side earned the profit: `trades.side_contribution`
- Fragile to costs: `performance.holding_period`, `costs.break_even`
- Is this just the market going up: `market.attribution`, `costs.break_even`, `context.published_factors`
- Return compared with the risk taken: `overfit_controls.required_history`, `overfit_controls.shrunk_sharpe`, `risk.kelly`, `risk.fractional_kelly`,
  `risk.optimal_f`, `risk.vol_target`, `performance.ulcer`, `performance.pain`, `performance.sterling_burke`, `performance.gain_to_pain`, `performance.kappa`,
  `performance.lo_sharpe`, `performance.cornish_fisher_sharpe`, `performance.payoff_expectancy`, `overfit_controls.probabilistic_sharpe`,
  `overfit_controls.min_track_record`, `performance.downside_ratios`
- Does it hold up out of sample: No toolbox check yet. `alpha test` reports the out-of-sample numbers.
- Would a slightly different data feed change the answer: No toolbox check yet. `alpha data health <ASSET>` reports the data's faults.
- Is this just a known published factor: `context.published_factors`
<!-- situations:end -->

Rule: [toolbox rules](../../docs/reference/invariants/cli-toolbox.md#finding-checks-and-recording-the-plan).
