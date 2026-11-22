---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/risk_sizing*.py
  - apps/alpha-cli/src/alpha_cli/toolbox/families/risk_common.py
---

# Risk, sizing and attribution checks

**Reach for these checks when** the owner asks how large a loss can get, what stake the trades support, or where the profit came from.
Run one with `alpha tool run <id> <run_id>`. Each gives a reading, never a pass or fail.

| Check | Question |
|---|---|
| `risk.parametric_var` | How large a loss does a bell-curve fit give for one bar? |
| `risk.cornish_fisher_var` | How much does skew and fat tails change the one-bar loss figure? |
| `risk.worst_windows` | What were the worst one, five and twenty-one bar losses? |
| `risk.tail_fit` | How heavy is the loss tail once the worst bars are fitted on their own? |
| `risk.var_coverage` | Did losses beyond the loss figure happen as often as the figure says? (Kupiec) |
| `risk.var_independence` | Do the loss-figure breaches bunch together? (Christoffersen) |
| `risk.kelly` | What stake per trade maximised long-run growth on these trades? |
| `risk.fractional_kelly` | How much growth and drawdown do full, half and quarter Kelly stakes give? |
| `risk.optimal_f` | What fixed fraction of the largest loss would have grown the trades fastest? (Vince) |
| `risk.loss_streaks` | How long a losing streak should this loss rate lead you to expect? |
| `risk.vol_target` | Does scaling the size to a constant volatility help? |
| `attribution.hold_period` | Do short or long holds earn more per trade? |
| `attribution.weekday` | Which weekday of entry earned the most per trade? |
| `attribution.drawdown_causes` | What happened during the deepest drawdown? |

**What these checks cannot tell you** They describe one history. Sizing checks treat each closed trade as an independent bet and
ignore overlapping trades, leverage cost and margin. With few trades or bars each check says "too little to read" and gives the count.
