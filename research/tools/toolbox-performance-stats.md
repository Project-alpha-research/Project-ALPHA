---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/performance_stats*.py
  - tests/unit/test_toolbox_performance_stats.py
verified: de18639e9d077263
---

# Performance statistics of one rule test

**Reach for these checks when** the owner asks how the return compares with the drawdown, the tails or the trades.
Each gives a reading, never a pass or a fail. Under 20 stored returns or 10 closed trades, a check says "too little to read".

| Question | Command |
|---|---|
| How painful was the drawdown path (ulcer index, Martin ratio)? | `alpha tool run performance.ulcer <run_id>` |
| How deep was the average drawdown (pain index and ratio)? | `alpha tool run performance.pain <run_id>` |
| Return per unit of the deepest drawdowns (Sterling, Burke)? | `alpha tool run performance.sterling_burke <run_id>` |
| How many times did net profit cover the worst drawdown? | `alpha tool run performance.recovery_factor <run_id>` |
| Total return per unit of summed losses? | `alpha tool run performance.gain_to_pain <run_id>` |
| Return against shortfalls below a threshold (kappa, upside potential)? | `alpha tool run performance.kappa <run_id>` |
| Yearly Sharpe ratio allowing for serial correlation (Lo)? | `alpha tool run performance.lo_sharpe <run_id>` |
| Sharpe ratio allowing for skew and fat tails? | `alpha tool run performance.cornish_fisher_sharpe <run_id>` |
| Worst one-bar, five-bar and twenty-one-bar returns? | `alpha tool run performance.worst_windows <run_id>` |
| Average winner against average loser, and the average trade? | `alpha tool run performance.payoff_expectancy <run_id>` |
| How long were the winning and losing streaks? | `alpha tool run performance.streaks <run_id>` |
| How long were trades held? | `alpha tool run performance.holding_period <run_id>` |

**How to read it**

- Equity checks use the stored walk-forward equity after costs; trade checks use the stored closed trades. Both stop before 2024-01-01.
- Expectancy counts one average loss as "R", because stored trades carry no stop distance.
- Sterling, Burke, Kappa and the Lo and Cornish-Fisher Sharpe fix one convention each; the output text states it.

Rule: [toolbox rules](../../docs/reference/invariants/cli-toolbox.md#finding-checks-and-recording-the-plan).
