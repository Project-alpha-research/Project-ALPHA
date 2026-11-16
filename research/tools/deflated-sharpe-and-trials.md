---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/*.py
  - apps/alpha-cli/src/alpha_cli/optim_cmds.py
verified: e1235a85a7c467ba
---

# Deflated Sharpe and trial counting

**Reach for it when** several settings, assets or ideas were tried and one looks good. More tries, luckier best.

**Commands**

```text
uv run alpha results --symbol <SYMBOL> --json
uv run alpha results cite <run_id> trial_dsr
uv run alpha results cite <run_id> total_trials
uv run alpha optim grid <SYMBOL> --strategy ma_crossover --grid fast=20,50 --grid slow=100,200
```

**How to read it**

- `dsr` is the gauntlet's deflated Sharpe for this run taken alone (one trial). `trial_dsr` deflates by the
  same-symbol trials in the ledger plus this run's sensitivity re-runs: prefer it. Both are probabilities
  between 0 and 1; the gauntlet's pass line is 0.95. A `null` comes with a `reason`.
- `total_trials` is the ledger count when the run was made; `variants_evaluated` counts its re-runs. Report
  "trial N of M recorded", and where this run ranks among the rows for the same rule and asset.
- `alpha optim grid` sweeps declared settings and prints the best one with its deflated Sharpe, `PBO` (the
  probability that the in-sample winner is below the middle out of sample; high is bad), and the `SPA` and
  `RC` p-values (is the best better than no skill, allowing for the search).

**What it cannot tell you**

- Trials nobody recorded: `alpha validate`, `alpha optim` and `alpha backtest` runs are not in the ledger; count them by hand, say the true number is higher.
- `alpha ledger summary` and `families` count every recorded try (rule tests, tools, RD-Agent) read-only and group related variants; the effective number
  of tests is not shown, and the Sharpe step does not use the count yet.

**Next** A setting that survives: check it against [the random-price null](random-price-null.md) and the
benchmark. A setting that does not: report it as best-of-many and stop tuning.
