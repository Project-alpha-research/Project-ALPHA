---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/monte_carlo_cmds.py
  - apps/alpha-cli/src/alpha_cli/risk_cmds.py
verified: 0c8b05351952
---

# Path risk: how bad could it get

**Reach for it when** the owner asks "how bad could it get?", "what drawdown should I expect?", or a result
rests on one history that could easily have unfolded differently.

**Commands**

```text
uv run alpha monte-carlo classical --from-run <run_id> --paths 10000
uv run alpha risk scenario --from-run <run_id> --periods-per-year 365 --json
```

**How to read it**

- `alpha monte-carlo classical` simulates new paths from the run's out-of-sample returns three ways (`iid_empirical`,
  `regime_switching`, `student_t`) and prints, for each: the median final value with a 5% to 95% range, the
  median and 95th-percentile drawdown, and the chance of a loss and of ruin (a 50% drawdown) with ranges.
  It writes a new run and prints its id.
- `alpha risk scenario` re-scores the stored equity curve under higher volatility and one-off shocks, with
  value at risk and expected shortfall. Pass the run's own bars per year (`periods_per_year` in the rule
  test output); it assumes 252 otherwise.
- Read the range, not the median. A wide range on a short history is the honest answer.

**What it cannot tell you**

- Anything the tested history did not contain: both tools re-use the run's own returns.
- It needs enough history: on a short run it stops with a message such as "training prefix ... cannot freeze
  a 63-session volatility boundary". Report that as "not computed: history too short".
- These numbers are not covered by `alpha results cite`; quote them with the run id and the output line.

**Next** A drawdown range the owner would not sit through: that is a judgement call. Ask them.
