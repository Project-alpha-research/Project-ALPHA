---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/cost_realism*.py
verified: 78e6a43af39bf282
---
# Cost and execution realism checks
**Reach for these checks when** a result may depend on fees, spreads, size, tax or how orders fill.
| Question | Command |
|---|---|
| How does the return change as trading costs rise? | `alpha tool run cost_realism.cost_sweep <run_id>` |
| How much of the return is left after the cost of trading so often? | `alpha tool run cost_realism.churn_budget <run_id>` |
| What does the borrowed money in the run's trades cost? | `alpha tool run cost_realism.financing_cost <run_id>` |
| What does the owner keep after tax? | `alpha tool run cost_realism.after_tax <run_id>` |
| What trading spread do the price bars imply? | `alpha tool run cost_realism.spread_estimates <run_id>` |
| What if stops fill at the next open after an overnight gap? | `alpha tool run cost_realism.gap_stress <run_id>` |
| How much would the size of these orders move the price? | `alpha tool run cost_realism.market_impact <run_id>` |
| How does the return change as more capital is deployed? | `alpha tool run cost_realism.capacity_curve <run_id>` |
| Do small orders pay realistic commission fees? | `alpha tool run cost_realism.commission_schedule <run_id>` |
| Does a small account's whole-share rounding change the trades? | `alpha tool run cost_realism.share_rounding <run_id>` |
| Does any order take too large a share of the day's volume? | `alpha tool run cost_realism.volume_share <run_id>` |
| Would a limit order below or above the open have filled on the entry day? | `alpha tool run cost_realism.limit_fill <run_id>` |
**How to read the results**
- Readings only, never pass or fail. Settings you choose are assumptions. A trade's size is its peak, so a scaled position is a bound; a gap has a reason.
- Recorded facts: `cost_realism.cost_sweep.return_x0`, `cost_realism.cost_sweep.return_x1`, `cost_realism.cost_sweep.return_x2`,
  `cost_realism.cost_sweep.return_x5`, `cost_realism.cost_sweep.sharpe_x1`, `cost_realism.cost_sweep.sharpe_x2`, `cost_realism.churn_budget.gross_return`,
  `cost_realism.churn_budget.net_return`, `cost_realism.churn_budget.trades_per_year`, `cost_realism.churn_budget.cost_drag_per_year`,
  `cost_realism.financing_cost.leveraged_trades`, `cost_realism.financing_cost.interest`, `cost_realism.financing_cost.profit_after_interest`,
  `cost_realism.after_tax.pre_tax_profit`, `cost_realism.after_tax.tax`, `cost_realism.after_tax.after_tax_profit`, `cost_realism.after_tax.wash_losses`,
  `cost_realism.spread_estimates.roll_bps`, `cost_realism.spread_estimates.corwin_schultz_bps`, `cost_realism.spread_estimates.abdi_ranaldo_bps`,
  `cost_realism.gap_stress.down_gap_share`, `cost_realism.gap_stress.down_extra_loss`, `cost_realism.gap_stress.worst_down_gap`,
  `cost_realism.market_impact.measured`, `cost_realism.market_impact.mean_impact_bps`, `cost_realism.market_impact.impact_cost`,
  `cost_realism.capacity_curve.return_x1`, `cost_realism.capacity_curve.return_x10`, `cost_realism.capacity_curve.return_x100`,
  `cost_realism.capacity_curve.zero_profit_multiple`, `cost_realism.commission_schedule.commission`, `cost_realism.commission_schedule.commission_bps`,
  `cost_realism.commission_schedule.min_ticket_share`, `cost_realism.share_rounding.trades`, `cost_realism.share_rounding.zero_share_trades`,
  `cost_realism.share_rounding.ideal_profit`, `cost_realism.share_rounding.rounded_profit`, `cost_realism.volume_share.measured`,
  `cost_realism.volume_share.over_cap`, `cost_realism.volume_share.max_participation`, `cost_realism.limit_fill.measured`,
  `cost_realism.limit_fill.touch_share`, `cost_realism.limit_fill.through_share`
**What these checks cannot tell you** A daily bar hides the order of prices in the day, queue position and real quotes. Models are rough averages.
**Next** [Break-even costs](run-level-checks.md); [cite a result](results-and-cite.md).
