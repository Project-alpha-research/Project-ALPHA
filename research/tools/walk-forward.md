---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/validate_cmds.py
  - apps/alpha-cli/src/alpha_cli/report_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/controls.py
verified: ac62963b39f729a3
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
**Efficiency**: `alpha diagnose <run_id>` stores `wfe`: per fold, out-of-sample CAGR over the full-sample
run's CAGR on that fold's recorded training window (warm-up bars trimmed; no new split). The median uses
the defined folds (`wfe_fold_count` of them); a warm-up-only or nonpositive in-sample fold is kept with its
reason. A practitioner rule of thumb, not a statistical test: no pass/fail threshold exists.

**What it cannot tell you**
- Whether the next period resembles the tested ones, or why a slice failed (see
  [benchmark and drawdowns](benchmark-and-drawdowns.md)).
- `alpha validate` changes slice sizes, defaults to 252 bars/year (`--periods-per-year`), has different sizing
  and writes no diagnostics or ledger trial. Count it by hand; it is not comparable with a rule test.

**Next** Read `by_year` in `alpha diagnose`, or [test more assets/history](rule-test.md) for more folds.
