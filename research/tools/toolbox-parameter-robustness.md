---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/families/parameter_robustness*.py
  - tests/unit/test_toolbox_parameter_robustness.py
---

# Parameter and specification robustness

**Reach for these checks when** you want to know if the result depends on the exact settings, the exact timing or the exact prices.

| Question | Command |
|---|---|
| How do the Sharpe ratio and return change when each setting moves alone? | `alpha tool run parameters.one_at_a_time <run_id>` |
| How much of a small grid of nearby settings stays near the chosen result? | `alpha tool run parameters.plateau <run_id>` |
| Do the nearest settings make money in the same direction? | `alpha tool run parameters.neighbour_stability <run_id>` |
| How weak is the weakest of the nearest settings? | `alpha tool run parameters.worst_neighbour <run_id>` |
| What if each entry came 1, 2 or 3 bars later? | `alpha tool run parameters.entry_delay <run_id>` |
| What if each exit came 1, 2 or 3 bars later? | `alpha tool run parameters.exit_delay <run_id>` |
| How far do results move if 10%, 20% or 30% of entries are skipped? | `alpha tool run parameters.skip_entries <run_id>` |
| What is left at 2, 3 and 5 times the fees and slippage? | `alpha tool run parameters.cost_ladder <run_id>` |
| What if the test had started 3, 6 or 12 months later? | `alpha tool run parameters.start_date <run_id>` |
| Does the opposite rule also look good? | `alpha tool run parameters.inversion <run_id>` |
| How much do results spread with a small nudge to every price? | `alpha tool run parameters.price_noise <run_id>` |

**How to read it**

- Each check runs the engine again on the run's own bars, before the held-back period, with one thing changed.
- Settings move to 0.5, 0.8, 1.2 and 1.5 times (one at a time), or 0.8 and 1.2 times (nearest). Windows stay whole bars.
- The grid moves the first two settings: `grid=quick` is 3 x 3 (8 re-runs), `grid=full` is 5 x 5 (24 re-runs).
- A settings check (the first four) adds tries: each setting goes in the trial ledger before it runs. A repeat adds none.
- The other seven are controls: the same rule on changed prices, timing or costs. They add no try.
- A run with fewer than 10 closed trades is too little to read. The check says so and runs nothing.
- Each check says how many engine runs it makes and about how long, then prints a line every 10 seconds.

**What these checks cannot tell you** They are full-sample re-runs, not walk-forward results. A stable result near your
settings does not show that an edge exists. None picks a best setting. A control does not pick a better variant: a changed rule is a new rule; test it as one.

**Next** [Sensitivity](sensitivity.md) for the stored variants. [Deflated Sharpe and trials](deflated-sharpe-and-trials.md).
