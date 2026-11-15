---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/validate_cmds.py
  - apps/alpha-cli/src/alpha_cli/report_cmds.py
verified: 0c8b05351952
---

# Walk-forward (out of sample)

**Reach for it when** a result may only fit the period it was tuned on, works in some years only, or the owner
asks "would this have held up later?". Every rule test already ran one: `oos_sharpe` is scored only on the
later, unseen slices.

**Commands**

```text
uv run alpha report <run_id>
uv run alpha figures render <run_id> --figure fold_sharpe
uv run alpha validate <SYMBOL> --strategy ma_crossover --param fast=50 --param slow=200 --train-size 504 --test-size 63
```

**How to read it**

- `alpha report` prints `walk-forward: <n> OOS folds`, the out-of-sample metrics, `CI[sharpe]` (a bootstrap
  range: a range that includes zero means the Sharpe is not distinguishable from nothing), the letter grade
  with its edge, robustness, risk and sample parts, and one `gate[...]` line per test, `PASS` or `FAIL`.
- The `fold_sharpe` chart shows each slice. One strong slice carrying the rest is a finding; say so.
- Few folds means little evidence, whatever the Sharpe. Two folds is a first look, not a result.

**What it cannot tell you**

- Whether the next period resembles the tested ones, or why a slice failed (see
  [benchmark and drawdowns](benchmark-and-drawdowns.md)).
- `alpha validate` is the older direct command: use it only to change slice sizes. It assumes 252 bars a year
  unless told (`--periods-per-year`), has its own sizing defaults, writes no diagnostics and is not counted
  in the ledger. Count those runs by hand, and say the result is not comparable with a rule test.

**Next** A weak slice: read `by_year` in `alpha diagnose`. A strong result on few folds: test more assets or
a longer history with the [rule test](rule-test.md).
