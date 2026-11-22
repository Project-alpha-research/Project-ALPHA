---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/costs.py
  - apps/alpha-cli/src/alpha_cli/toolbox/families/performance.py
  - apps/alpha-cli/src/alpha_cli/toolbox/families/robustness.py
  - apps/alpha-cli/src/alpha_cli/toolbox/families/trades.py
  - tests/unit/test_toolbox_run_level_checks.py
verified: 67c21050f541ec73
---
# Costs, downside risk, date sensitivity and closed trades
**Reach for these checks when** a rule-test result depends on costs, dates, losses or a few profitable trades.

| Question | Command |
|---|---|
| How much higher could costs be before the result breaks even or matches buy and hold? | `alpha tool run costs.break_even <run_id>` |
| How large was the return relative to losses? | `alpha tool run performance.downside_ratios <run_id>` |
| Would different start and end dates change the result? | `alpha tool run robustness.start_end_dates <run_id>` |
| Which side contributed the profit? | `alpha tool run trades.side_contribution <run_id>` |
| Do wins and losses cluster or alternate in entry order? | `alpha tool run trades.dependence <run_id>` |
| How much profit survives removing the best trades? | `alpha tool run trades.concentration <run_id>` |

**How to read the results**
- Break-even cost: the multiple (0 to 100) of each scored bar's recorded costs at which the compounded return is nil, or equals buy and hold.
- Sortino: mean bar return over the root mean square of losses below zero (taken over all bars), times the square root of bars per year.
  Calmar: whole-run compound yearly return over the deepest drop. Omega at zero: summed gains over summed losses. Tail ratio: 95th percentile
  return over the size of the fifth-percentile loss. Read them beside the stored out-of-sample Sharpe.
- Unavailable with a reason, never zero or infinite: fewer than two returns; no losing bars (Sortino, Calmar, Omega); a fifth percentile that is not a loss.
- The date check cuts the stored walk-forward curve at five starts and five ends, months apart. Each window has its own buy-and-hold on the run's price basis.
  Use `--param step_months=1` for monthly cuts. Changing the three-month default counts as another setting.
- Cost share: total costs over before-cost profit, when positive. Trades sum after-cost profit in account currency, uncompounded.
  A missing side has no measured average. Shares are unavailable when total profit is zero or negative, and can exceed 100% when the other trades lost money.
- Removing the best trades needs at least one trade left; the best tenth needs ten trades and rounds up to whole trades.
- Streaks: wins and losses in entry order. Fewer than random means they bunched, more that they alternated; a p-value below 0.05 says the order
  was probably not random. Needs three trades with a win and a loss. The z-score matches `alpha figures render <run_id> --figure trade_runs_test`.

**What these checks cannot tell you**
The streak test sees only win or loss, not size or cause. The windows overlap. Neither a window nor a trade-removal calculation tests the rule on fresh data.
Removing trades cannot predict later sizes. Scaling costs cannot model stressed spreads, partial fills or whole-share rounding.
**Next** Read the [stored results and citation instructions](results-and-cite.md) to quote a finding with its run labels.
