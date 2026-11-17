---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/report_cmds.py
  - apps/alpha-cli/src/alpha_cli/optim_cmds.py
verified: d45a9de03ba698e9
---

# Random-price null

**Reach for it when** the result looks too good, or the question is "could a rule like this score as well on
prices with no pattern in them?". Every rule test already ran it, at three levels of realism.

**Commands**

```text
uv run alpha report <run_id>
uv run alpha figures render <run_id> --figure null_distribution
uv run alpha optim mcpt <SYMBOL> --strategy ma_crossover --grid fast=20,50 --grid slow=100,200 --perms 100
```

**How to read it**

- `alpha report` prints three lines, `null[returns_level]`, `null[full_engine]` and `null[bar_permutation]`,
  each with `percentile` (the share of random-price paths the strategy beat), a p-value and `PASS` or `FAIL`.
  A pass needs the percentile at or above the threshold (0.95 unless changed). `gate[randomized_price_null]`
  is the combined line.
- A `FAIL` says the result is within what chance produces on these bars. Report it as that, plainly.
- A `quick` run uses very few random paths (20, 4 and 4): its percentiles are coarse. Re-run without `--quick`
  before leaning on them.
- `alpha optim mcpt` asks the same of a whole parameter sweep: it re-optimises on shuffled bars. Its own output
  says "overfit test only, not OOS evidence". It is not counted in the ledger.

**What it cannot tell you**

- That an edge exists. Beating random prices is necessary, not sufficient: costs, the benchmark and the number
  of tries still apply.
- Anything about dates: random-date and market-drift controls for event ideas are not available yet.

**Next** A pass on a best-of-many setting: [deflated Sharpe and trials](deflated-sharpe-and-trials.md).
