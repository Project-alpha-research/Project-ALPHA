---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/*.py
  - apps/alpha-cli/src/alpha_cli/optim_cmds.py
verified: 139da8784b062844
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

- Trials nobody recorded. Runs from `alpha validate`, `alpha optim` and `alpha backtest` are not in the
  ledger: count them by hand and say the true number of tries is higher.
- Related variants are not yet grouped into one family, so the effective number of tests is not shown.
- `alpha ledger summary` and `alpha ledger families` count every recorded try across rule tests, tools and the
  RD-Agent factor ledger in one read-only view; rows it cannot read are shown and still counted. The Sharpe
  step does not use that count yet.

**Next** A setting that survives: check it against [the random-price null](random-price-null.md) and the
benchmark. A setting that does not: report it as best-of-many and stop tuning.
