---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/facts.py
verified: 6f93ec84bbaaa607
---

# Results and cite

**Reach for it when** the owner asks about past work, before proposing a test (was it tried?), and every time
a number goes into an answer.

**Commands**

```text
uv run alpha results --symbol SPY --name <test name> --limit 50 --json
uv run alpha results show <run_id> --json
uv run alpha results cite <run_id> <metric>
```

**How to read it**

- `alpha results` lists ledger rows, newest first, failed attempts included, and `total_trials`.
- `show` takes a run id or a test id and returns per run: `facts`, `labels`, `flags`, `audit` and `charts`.
- `cite` prints one stored value with its tag and basis: `<value> [<run_id>:<metric>] (<basis>)`. Paste the tag.
  With `--json` it returns the fact: `metric`, `value`, `run_id`, `basis`, `source`, `labels`, `reason`.
- Metrics: `verdict`, `oos_sharpe`, `dsr`, `full_sample_total_return`, `full_sample_cagr`, `full_sample_sharpe`,
  `full_sample_max_drawdown`, `benchmark_total_return`, `benchmark_cagr`, `benchmark_sharpe`,
  `benchmark_max_drawdown`, `trades`, `exposure`, `top_1_profit_share`, `top_3_profit_share`,
  `delay_base_sharpe`, `delayed_sharpe`, `total_trials`, `trial_dsr`, `variants_evaluated`.

**What it cannot tell you**

- Anything not stored. `cite` never computes: a missing value is `null` with a `reason`; an unknown metric returns `UNKNOWN_METRIC`.
- It needs the full run id; a shortened id returns `UNKNOWN_RUN`.
- It cannot search by words or compare two runs. Filter with `--symbol` or `--name` and quote both numbers.
- Runs made by older commands are not in the list; `cite` still reads their gauntlet metrics.

**Next** No row for the question: say "not tested" and offer the [rule test](rule-test.md).
