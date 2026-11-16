---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/*.py
  - apps/alpha-cli/src/alpha_cli/optim_cmds.py
verified: 8f886d19794ff853
---

# Deflated Sharpe and trial counting

**Reach for it when** several settings, assets or ideas were tried and one looks good. More tries, luckier best.

**Commands**
```text
uv run alpha results --symbol <SYMBOL> --json
uv run alpha results cite <run_id> trial_dsr
uv run alpha results cite <run_id> family_trials
uv run alpha optim grid <SYMBOL> --strategy ma_crossover --grid fast=20,50 --grid slow=100,200
```

**How to read it**
- `trial_dsr` uses the idea family's ledger count and variance from available same-symbol Sharpes and variants.
  `dsr` feeds the verdict using same-bar-size family Sharpes and at least that count; its `trial_basis`
  names the family or explicitly says no family was found. Both are probabilities; the pass line is 0.95. `null` has a reason.
- Cite `family_trials` for the count at the run: prior family trials, this run, scored variants and unknown
  rows, never below the available Sharpes. `alpha results show` also shows live family counts.
- `total_trials` is the ledger count when the run was made; `variants_evaluated` counts its re-runs. Report
  "trial N of M recorded", and where this run ranks among the rows for the same rule and asset.
- `alpha optim grid` sweeps declared settings and prints the best one with its deflated Sharpe, `PBO` (the
  probability that the in-sample winner is below the middle out of sample; high is bad), and the `SPA` and
  `RC` p-values (is the best better than no skill, allowing for the search).

**What it cannot tell you**

- Trials nobody recorded: `alpha validate`, `alpha optim` and `alpha backtest` runs are not in the ledger; count them by hand, say the true number is higher.
- `alpha ledger summary` and `families` count every recorded try (rule tests, tools, RD-Agent) read-only and group related variants; the effective number
  of tests is not shown. Family counting is used by the rule-test Sharpe and verdict.

**Next** A setting that survives: check it against [the random-price null](random-price-null.md) and the
benchmark. A setting that does not: report it as best-of-many and stop tuning.
