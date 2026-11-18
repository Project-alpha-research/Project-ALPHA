---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/facts.py
  - apps/alpha-cli/src/alpha_cli/toolbox/registry.py
verified: a139ec7ac9b14a66
---
# Results and cite
**Reach for it when** citing a run. `uv run alpha results --symbol SPY --name <test name> --limit 50 --json`, `alpha results show <run_id> --json`,
`uv run alpha results cite <run_id> <metric>`, `uv run alpha results compare <run_id> <run_id>`, `uv run alpha results check <file>`.
**How to read it** Show includes labels, audits and family counts. Compare two to eight runs against the first for differences and ratios. Check the draft.
Paste `<value> [<run_id>:<metric>] (<basis>)`. For multiple outputs or non-default settings use `--tool-output <id>` and quote “1 of N settings tried”.
- `data_period`, `traded_period`, `verdict`, `oos_sharpe`, `psr`, `dsr`, `full_sample_total_return`, `full_sample_cagr`, `full_sample_sharpe`,
  `full_sample_max_drawdown`, `benchmark_total_return`, `benchmark_cagr`, `benchmark_sharpe`, `benchmark_max_drawdown`, `inverted_sharpe`,
  `inverted_sharpe_se`, `inverted_total_return`, `inverted_trades`, `inverted_label`, `wfe`, `wfe_fold_count`, `resized_entries`, `trades`, `exposure`,
  `top_1_profit_share`, `top_3_profit_share`, `delay_base_sharpe`, `delayed_sharpe`, `total_trials`, `trial_dsr`, `family_trials`, `variants_evaluated`,
  `price_noise_median_sharpe`, `price_noise_p05_sharpe`, `price_noise_p95_sharpe`, `price_noise_sign_flip_share`, `price_noise_median_trades`.
- `market_beta`, `market_alpha_annual`, `market_alpha_p`, `market_r_squared`, `regime_turbulent_share_of_return`, `regime_turbulent_share_of_time`,
  `changepoint_count`, `market.changepoints.count`, `market.attribution.beta`, `market.attribution.alpha_annual`,
  `market.attribution.alpha_p`, `market.attribution.r_squared`, `market.vol_regimes.turbulent_share_of_return`, `market.vol_regimes.turbulent_share_of_time`.
- `performance.downside_ratios.sortino`, `performance.downside_ratios.calmar`, `performance.downside_ratios.omega`, `performance.downside_ratios.tail_ratio`,
  `performance.downside_ratios.sharpe`, `robustness.start_end_dates.total_return_min`, `robustness.start_end_dates.total_return_max`,
  `robustness.start_end_dates.cagr_min`, `robustness.start_end_dates.cagr_max`, `robustness.start_end_dates.sharpe_min`,
  `robustness.start_end_dates.sharpe_max`, `robustness.start_end_dates.max_drawdown_min`, `robustness.start_end_dates.max_drawdown_max`,
  `robustness.start_end_dates.positive_share`, `robustness.start_end_dates.beat_hold_share`, `trades.side_contribution.sides`,
  `trades.side_contribution.long_count`, `trades.side_contribution.long_profit_share`, `trades.side_contribution.long_win_rate`,
  `trades.side_contribution.long_average_pnl`, `trades.side_contribution.short_count`, `trades.side_contribution.short_profit_share`,
  `trades.side_contribution.short_win_rate`, `trades.side_contribution.short_average_pnl`, `trades.concentration.without_best_1`,
  `trades.concentration.without_best_3`, `trades.concentration.without_best_5`, `trades.concentration.top_decile_share`, `costs.break_even.zero_multiple`,
  `costs.break_even.hold_multiple`, `costs.break_even.cost_share`, `costs.break_even.sentence`. [Run-level definitions](run-level-checks.md).
- `resampling.block_bootstrap_paths.drop_q95`, `resampling.drawdown_distribution.median`, `resampling.drawdown_distribution.observed`,
  `resampling.block_bootstrap_paths.high`, `resampling.block_bootstrap_paths.median`, `resampling.drawdown_distribution.q95`, `trades.dependence.expected`,
  `overfit.deflated_sharpe.benchmark`, `resampling.block_bootstrap_paths.low`, `resampling.sharpe_interval.lower`, `resampling.sharpe_interval.point`,
  `resampling.return_interval.lower`, `resampling.return_interval.point`, `resampling.return_interval.upper`, `resampling.sharpe_interval.upper`,
  `overfit.deflated_sharpe.dsr`, `overfit.deflated_sharpe.trials`, `trades.dependence.p_value`, `trades.dependence.runs`, `trades.dependence.z`.
- `setup_occurrences`, `setup_mean_net_return`, `setup_median_net_return`, `setup_hit_rate`, `setup_excess_over_drift`, `setup_random_date_p`, `setup_trades`,
  `setup_trade_mean_net_return`, `setup_trade_hit_rate`, `setup_trade_mean_bars_held`, `setup_trade_excess_over_drift`, `setup_trade_random_date_p`,
  `setup_trade_mean_r` ([setup study](setup-study.md), [setup trade](setup-trade.md)).
**What it cannot tell you** `cite` never computes (a gap is `null` + reason); no logic check. **Next** No row: say "not tested"; offer a [test](rule-test.md).
