---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/facts.py
verified: 883f23d4915715d7
---
# Results and cite
**Reach for it when** the owner asks about past work, before proposing a test (was it tried?), and every time a number goes into an answer.
**Commands**
```text
uv run alpha results --symbol SPY --name <test name> --limit 50 --json
uv run alpha results show <run_id> --json
uv run alpha results cite <run_id> <metric>
uv run alpha results compare <run_id> <run_id>
uv run alpha results check <file>
```
**How to read it**
- `alpha results` lists ledger rows (newest first, failures too) and `total_trials`; `show <id>`: `facts`, `labels`, `flags`, `audit`, `charts`,
  `tools`, `family` (recorded and live family counts); for a test id, failed assets under `failed` with a reason.
- `cite` prints one stored value with its tag and basis: `<value> [<run_id>:<metric>] (<basis>)`. Paste the tag. `--json` gives `metric`, `value`,
  `run_id`, `basis`, `source`, `labels`, `reason`.
- `compare` (two to eight runs, first is the base) gives each run's `value`, `diff`, `ratio`. `check` reads a draft tagged `0.75 [<run_id>:<metric>]`;
  fix the draft on `ROUNDED_ACROSS_THRESHOLD`, `FLAG_CONTRADICTED`, `UNIT_MISMATCH`, `PRECISION_TOO_LOW` or `METRIC_NOT_STORED`.
- Metrics: `data_period`, `traded_period`, `verdict`, `oos_sharpe`, `dsr`, `full_sample_total_return`, `full_sample_cagr`, `full_sample_sharpe`,
  `full_sample_max_drawdown`, `benchmark_total_return`, `benchmark_cagr`, `benchmark_sharpe`, `benchmark_max_drawdown`, `resized_entries`, `trades`,
  `exposure`, `top_1_profit_share`, `top_3_profit_share`, `delay_base_sharpe`, `delayed_sharpe`, `total_trials`, `family_trials`, `trial_dsr`,
  `variants_evaluated`, `inverted_sharpe`, `inverted_sharpe_se`, `inverted_total_return`, `inverted_trades`, `inverted_label`, `wfe`, `wfe_fold_count`.
  WFE is a practitioner rule of thumb, not a statistical test; `wfe_fold_count` counts the folds in its median.
  [Tool](attribution-regimes-changepoints.md) facts take `--tool-output <id>` when a tool ran twice: `market_beta`, `market_alpha_annual`,
  `market_alpha_p`, `market_r_squared`, `regime_turbulent_share_of_return`, `regime_turbulent_share_of_time`, `changepoint_count`.
- Setup study ids support cite/check: `setup_occurrences`, `setup_mean_net_return`, `setup_median_net_return`,
  `setup_hit_rate`, `setup_excess_over_drift`, `setup_random_date_p` ([limits](setup-study.md)).
- Trade facts: `setup_trades`, `setup_trade_mean_net_return`, `setup_trade_hit_rate`, `setup_trade_mean_bars_held`,
  `setup_trade_excess_over_drift`, `setup_trade_random_date_p`, `setup_trade_mean_r` ([limits](setup-trade.md)).
**What it cannot tell you**
- `cite` never computes: missing values are `null` with reasons; unknown metric/id: `UNKNOWN_METRIC` / `UNKNOWN_RUN`.
  No word search (use `--symbol` or `--name`); `check` cannot judge reasoning.
**Next** No row for the question: say "not tested" and offer the [rule test](rule-test.md).
