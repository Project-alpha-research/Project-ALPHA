---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/*.py
  - apps/alpha-cli/src/alpha_cli/optim_cmds.py
verified: 7ee73e186a583b2c
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
- `trial_dsr` and the verdict's `dsr` use the same inputs (equal after a rule test): spread from the idea
  family's distinct same-bar-size Sharpes and this run, N from the family count; its `trial_basis`
  names the family, repeats not counted and a floored spread (under 5 comparable trials), or says no family
  was found. Pass line 0.95. Variants count in N but stay out of the spread: full-sample, neighbouring, correlated.
- Cite `family_trials` for the count at the run: prior family trials, this run, scored variants and unknown
  rows, never below the available Sharpes. `alpha results show` also shows live family counts.
- `total_trials` is the ledger count when the run was made; `variants_evaluated` counts sensitivity re-runs only; the inverted control is not a trial. Report
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
