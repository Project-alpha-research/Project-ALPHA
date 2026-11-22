---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/regimes.py
  - apps/alpha-cli/src/alpha_cli/toolbox/families/regimes_*.py
  - tests/unit/test_toolbox_regimes.py
verified: 0000000000000000
---

# Regime and conditional checks

**Reach for these checks when** the owner asks whether a rule works in all kinds of time: every year, both halves, each
weekday or month, rising and falling markets, or before and after a change. Each gives a reading, never a pass or fail.
Run one with `alpha tool run <id> <run_id>`. Each needs a stored rule-test run; the market checks also need its stored
buy-and-hold line.

| Check | Question |
|---|---|
| `regimes.year_by_year` | Does it work in most years or only a few? |
| `regimes.sub_period_stability` | Do the early and late halves of the history agree? |
| `regimes.day_of_week` | Do certain weekdays earn more than the others? |
| `regimes.calendar_month` | Do certain calendar months earn more than the others? |
| `regimes.turn_of_month` | Do the bars around the turn of the month earn more than the others? |
| `regimes.halloween` | Does it earn more from November to April than from May to October? |
| `regimes.bull_bear` | Does it earn in both rising and falling markets? |
| `regimes.trend_range` | Does it earn in trending markets, in sideways markets, or both? |
| `regimes.asymmetric_beta` | Is the market exposure larger on down bars than on up bars? |
| `regimes.chow_test` | Did the average return change at a date I chose? |
| `regimes.cusum_mean` | Has the average return drifted over the history? |
| `regimes.cusum_variance` | Has the size of the return swings changed over the history? |
| `regimes.sup_f` | Is there a break in the average return at a date I did not name? |
| `regimes.break_count` | How many breaks in the average return, and where? |

**How to read them**

- Each return is dated at the open that starts its bar. A group with too few bars gives "too little to read" with the count.
- A two-group gap comes with a Welch p-value; weekday and month use a rank test. Many splits make a small p-value cheap.
- `regimes.sup_f` draws seeded random histories for its p-value. The other checks are exact.

**What these checks cannot tell you** They describe the past, not why. Neighbouring bars are not independent, so p-values are rough.
For volatility regimes and change points see `market.vol_regimes` and `market.changepoints`.
