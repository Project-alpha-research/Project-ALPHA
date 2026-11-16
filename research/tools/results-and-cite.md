---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/facts.py
verified: a26b6d400248c33a
---

# Results and cite

**Reach for it when** the owner asks about past work, before proposing a test (was it tried?), and every time a number goes into an answer.

**Commands**
```text
uv run alpha results --symbol SPY --name <test name> --limit 50 --json
uv run alpha results show <run_id> --json
uv run alpha results cite <run_id> <metric>
uv run alpha results compare <run_id> <run_id>
uv run alpha results check <file>
```

**How to read it**

- `alpha results` lists ledger rows (newest first, failures too) and `total_trials`; `show <id>`: `facts`, `labels`, `flags`, `audit`, `charts`,
  `family` (recorded count and live family counts).
- `cite` prints one stored value with its tag and basis: `<value> [<run_id>:<metric>] (<basis>)`. Paste the tag. `--json` gives `metric`, `value`,
  `run_id`, `basis`, `source`, `labels`, `reason`.
- `compare` (two to eight runs, first is the base) gives each run's `value`, `diff`, `ratio`. `check` reads a draft whose numbers are tagged
  `0.75 [<run_id>:<metric>]` and reports each mismatch.
- `ROUNDED_ACROSS_THRESHOLD`, `FLAG_CONTRADICTED`, `UNIT_MISMATCH`, `PRECISION_TOO_LOW`, `METRIC_NOT_STORED`: fix the draft.
- Metrics: `verdict`, `oos_sharpe`, `dsr`, `full_sample_total_return`, `full_sample_cagr`, `full_sample_sharpe`, `full_sample_max_drawdown`,
  `benchmark_total_return`, `benchmark_cagr`, `benchmark_sharpe`, `benchmark_max_drawdown`, `trades`, `exposure`, `top_1_profit_share`,
  `top_3_profit_share`, `delay_base_sharpe`, `delayed_sharpe`, `total_trials`, `family_trials`, `trial_dsr`, `variants_evaluated`.

**What it cannot tell you**

- Anything not stored. `cite` never computes: a missing value is `null` with a `reason`; an unknown metric is `UNKNOWN_METRIC`; a short run id
  is `UNKNOWN_RUN`. It cannot search by words (filter with `--symbol` or `--name`). `check` does not judge reasoning.

**Next** No row for the question: say "not tested" and offer the [rule test](rule-test.md).
