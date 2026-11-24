---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/report_cmds.py
  - apps/alpha-cli/src/alpha_cli/optim_cmds.py
verified: 155885463133bffa
---

# Random-price null

**Reach for it when** the result looks too good, or the question is "could a rule like this score as well on
prices with no pattern in them?". Every rule test already ran it, at three levels of realism.

**Commands**
```text
alpha report <run_id>
alpha figures render <run_id> --figure null_distribution
alpha optim mcpt <SYMBOL> --strategy ma_crossover --grid fast=20,50 --grid slow=100,200 --perms 100
```
**How to read it**

- For a rule test, `alpha report` prints one line, "Random-data check": random prices did as well as the rule in up to a
  stated share of draws, in the weakest of the three levels. The higher the share, the more chance explains. `--json` holds
  `nulls`: one entry per level (`returns_level`, `full_engine`, `bar_permutation`) with `percentile` and `p_value`.
- A high share of random draws that did as well says the result is within what chance produces on these bars. Report it as that, plainly.
- A `quick` run uses very few random paths (20, 4 and 4): its percentiles are coarse. Re-run without `--quick`
  before leaning on them.
- `alpha optim mcpt` asks the same of a whole parameter sweep: it re-optimises on shuffled bars. Its own output
  says "overfit test only, not OOS evidence". It is not counted in the ledger.

**What it cannot tell you**

- That an edge exists. Beating random prices is necessary, not sufficient: costs, the benchmark and the number
  of tries still apply.
- Anything about dates. For random-date and drift controls on event ideas, use a [setup study](setup-study.md).

**Next** A pass on a best-of-many setting: [deflated Sharpe and trials](deflated-sharpe-and-trials.md).
