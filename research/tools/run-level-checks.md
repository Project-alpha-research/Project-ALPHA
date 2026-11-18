---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/performance.py
  - apps/alpha-cli/src/alpha_cli/toolbox/families/robustness.py
  - tests/unit/test_toolbox_run_level_checks.py
verified: e602bfd351a7132a
---

# Downside risk, date sensitivity and closed trades

**Reach for these checks when** a rule-test result depends on its dates, its worst days or a few profitable trades.

| Question | Command |
|---|---|
| How large was the return relative to losses? | `alpha tool run performance.downside_ratios <run_id>` |
| Would different start and end dates change the result? | `alpha tool run robustness.start_end_dates <run_id>` |
| Which side contributed the profit? | `alpha tool run trades.side_contribution <run_id>` |
| How much profit survives removing the best trades? | `alpha tool run trades.concentration <run_id>` |

**How to read the results**

- Sortino: mean bar return over the root mean square of losses below zero (taken over all bars), times the square root of bars per year.
  Calmar: whole-run compound yearly return over the deepest drop. Omega at zero: summed gains over summed losses. Tail ratio: 95th percentile
  return over the size of the fifth-percentile loss. Read them beside the stored out-of-sample Sharpe.
- Unavailable with a reason, never zero or infinite: fewer than two returns; no losing bars (Sortino, Calmar, Omega); a fifth percentile that is not a loss.
- The date check cuts the stored walk-forward curve at five starts and five ends, calendar months apart. Each window has its own matched buy-and-hold return.
  Use `--param step_months=1` for monthly cuts. Changing the three-month default counts as another setting.
- Trade figures sum after-cost profit in account currency; nothing is compounded. A missing side has no measured average.
  Shares are unavailable when total profit is zero or negative, and can exceed 100% when the other trades lost money.
- Removing the best trades needs at least one trade left; the best tenth needs ten trades and rounds up to whole trades.

**What these checks cannot tell you**

The windows overlap. Neither a window nor a trade-removal calculation tests the rule on fresh data.
Removing historical profits from a sum cannot predict how future position sizes would change.

**Next** Read the [stored results and citation instructions](results-and-cite.md) to quote a finding with its run labels.
