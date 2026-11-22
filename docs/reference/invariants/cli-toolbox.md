---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/**/*.py
  - apps/alpha-cli/src/alpha_cli/tool_cmds.py
  - apps/alpha-cli/src/alpha_cli/_rdagent_checks.py
  - tests/unit/test_toolbox_*.py
verified: a9b38e6041cf26ee
---

# Command line toolbox

Rules for the toolbox catalogue behind `alpha tool`: which checks are registered, how to add one and the honesty rules
for runs. The rules for follow-up tools on one rule test are in [cli-investigation-tools.md](cli-investigation-
tools.md). Why the toolbox exists: [toolbox](../project/components/toolbox.md).

## Adding a check

1. Write a `ToolSpec` (`toolbox/contract.py`) in a module under `toolbox/families/` (`context`, `costs`, `market`, `overfit`,
   `overfit_controls`, `performance`, `resampling`, `robustness`, `trades`).
2. Add it to the explicit tuple `SPECS` in `toolbox/registry.py`. Nothing is found automatically. The first sixteen
   registered ids: `market.attribution`, `market.vol_regimes`, `market.changepoints`, `performance.downside_ratios`,
   `robustness.start_end_dates`, `trades.side_contribution`, `trades.concentration`, `costs.break_even`,
   `resampling.sharpe_interval`, `resampling.return_interval`, `resampling.drawdown_distribution`,
   `trades.dependence`, `overfit.deflated_sharpe`, `resampling.block_bootstrap_paths`, `resampling.student_t_paths`, `context.published_factors`.
   The `overfit_controls` family adds eleven more ids (its [card](../../../research/tools/toolbox-overfit-controls.md)).
   Named sets and their execution order live in `toolbox/sets.py`.
3. The entry declares its id, version, question, kind, required inputs (`needs`), settings, outputs (key, label, unit,
   gloss), reading, caveats, cost class, seeded or not, time safety, look class, a poison test when time order
   matters, and `reference`: the test that checks its numbers.
4. The contract refuses: an id that is not lower-case `family.name`; a reading that names something that is not an
   output; a `search` look without an evaluation count; an ordered input without a poison test; repeated output or
   setting names; a gate that is not in the frozen list (empty).
5. Add the reference test under `tests/unit/test_toolbox_*.py` with a known answer. Call `alpha_validation` or a
   library for the statistics.
6. If the entry replaces an old command and card, delete them in the same pull request.

## Honesty rules

For RD-Agent, every idea with a shown trading replay and recorded evidence gets the set `rdagent-post-judge`, pass or
fail: `resampling.sharpe_interval` then `resampling.block_bootstrap_paths`, default settings, seed 0. Ideas stopped
earlier get no checks. The series is the verdict's own: the lead clock's daily after-cost return of the top third
above the average of all coins, read from the hash-verified replay. Five honesty rules hold: (1) the set is declared
in `toolbox/sets.py` before any result; (2) every attempt is logged in the run's `checks/ledger/trials.jsonl`; (3) the
checks add zero deflation trials and zero factor-ledger rows; (4) they cannot change a verdict; (5) every input ends
before the reserved date, else the check is refused. Outputs live in `checks/diagnostics/<target>/`. Readings reach
the agent's feedback and journey step 7 as information, not a target. The JSON `basis` field still names rule-test
equity; the `excess-over-equal-weight-basket` label marks the factor series.

## Registered checks

Sixteen entries make the first batch. Three describe one recorded rule test. `market.attribution` measures exposure against
full-history buy and hold, including eligible cash dividends. `market.vol_regimes` compares calm and turbulent
markets. `market.changepoints` identifies when behaviour shifted. The named set `market-context` runs all three. Five
more read the run's stored walk-forward files instead of replaying it: `performance.downside_ratios` (Sortino, Calmar,
Omega, tail ratio beside the stored Sharpe), `robustness.start_end_dates` (25 windows with moved first and last dates,
against buy and hold), `trades.side_contribution` (long versus short), `trades.concentration` (profit without the best
trades) and `costs.break_even` (cost multiples at zero return and at buy and hold). Their
[card](../../../research/tools/run-level-checks.md) gives the definitions. Seven tests use the same stored history. The
[resampling card](../../../research/tools/resampling-checks.md) and
[Monte Carlo card](../../../research/tools/montecarlo-checks.md) cover Sharpe and compound yearly return intervals,
independent-return drawdowns, and final returns and drops from block-bootstrap and Student-t redraws. The Student-t check
is available to RD-Agent but not in `rdagent-post-judge`. `trades.dependence` tests the order of
closed-trade outcomes. `overfit.deflated_sharpe` reuses the verdict's family correction on the ledger count and prior
comparable Sharpes frozen in the run, and states that count. See the [family counting
card](../../../research/tools/deflated-sharpe-and-trials.md).
`overfit_controls.*` are eleven readings on a finished run's scored returns or trades: probabilistic Sharpe, record length,
Bonferroni haircut, backtest length, best-of-noise Sharpe, deflated probability at a stated try count, t-statistic reference, trade
count, required history, a sequential test and a shrunk Sharpe. `n_trials` 0 uses the count recorded in the manifest.

`context.published_factors` sets a run's complete calendar-month returns beside the stored monthly long-short returns
of published US stock signals (source `osap-portfolios`): a joint reading on seven fixed well-known factors, and a
separate search across all signals marked exploratory. It never gives a pass or fail. It does not apply to assets that
are not US stocks or ETFs by the stored dataset identity. See the
[card](../../../research/tools/published-factors.md).

## Descriptive reference reads

A check that only describes a past result, and is never an input to a strategy, may read reference series for the
test's own period although those series became public later (owner, 2026-11-20). Its result carries the label
`reference-series-known-later` and the sentence "The reference factors were published as a data set after this test's
period. This is a description of the result made later, not something the strategy could have used." Strategy inputs
keep the strict known-at rule. The one read helper is `read_reference_for_period` in `toolbox/reference.py`. It takes
the newest stored vintage and names it, never returns a month at or after the held-back date, and never returns a month
whose end is after the run's last scored date. Only a descriptive hindsight diagnostic may declare the
`reference_factors` input, and the runner labels each of its results. `tests/unit/test_reference_read_structural_guard.py`
fails if any other module imports the helper's module or names the helper, under any alias; `toolbox/inputs.py` may
import only the vintage fingerprint for the cache key.

A descriptive reading that applies only to US stocks and funds decides this from the stored dataset identity. Older
stores record no identity, only the source name. For them `us_asset_class` in `toolbox/run_months.py` infers a
US-listed stock or fund when the source is a stock source (`EQUITY_PROVIDERS`) and every stored bar date is a session
of the US equity calendar (XNYS). The result carries the label `asset-kind-inferred-from-calendar` and the sentence
"This data set does not record what kind of asset it is. It was traded on a US stock exchange calendar, so it is
treated as a US-listed stock or fund." The fund caution is always printed for it. A crypto source is not applicable;
anything else is "cannot tell". The ticker text is never read. The entry's version is part of the result's key.

Each stored file's hash is part of the result's key, and a value that cannot be measured is "unavailable" with a
reason. Commands: `alpha tool list` (filter by `--for <run>`, `--search`, `--family`, `--kind`), `describe`, `run`,
`run-set` and `history`. The CLI takes a rule-test run id. The toolbox uses the [shared reserved
date](../project/reserved-period.md). Results are stored under the data directory's `diagnostics/<run>/`. See the
capability on [STATUS.md](../../../STATUS.md).

## Not built and outstanding

**Not built from this batch:**
- `trades.win_rate_interval`: Wilson bounds accept win and trade counts. No public validation function computes the
  comparison rate from average realized gains and losses. The barrier break-even rate uses a fixed target and stop. It
  answers a different question.
- `resampling.bar_permutation`: the run stores the observed and null scores, but the public permutation test needs
  OHLC bars and a callable that re-scores the strategy on each new permutation. There is no public validation function
  to rank the stored scores alone.
- `resampling.regime_paths`: the classical command labels calm and stormy bars from the market's closes. A check on
  stored equity gets no market series, and a factor replay has none. Labels from the strategy's own return swings
  would mostly mark in-market versus flat bars, not market regimes. It waits for an input that joins stored equity
  with the run's market closes.

The RD-Agent checks replace no existing command, card or verdict. Later one-in-one-out candidates are the interval
lines in `alpha report`, the IID drawdown summary in `alpha monte-carlo classical`, the runs z-score shown by `alpha
figures render` and the family DSR reported by `alpha results cite`. Each command also serves other uses.

**Other work outstanding:** letting the agent name checks in its proposal before judging, showing checks in the
proposal discussion, and more input adapters. Other gaps include a Workstation and MCP listing, a generated catalogue, counting sweep variants in
deflation, a budget for agent-selected checks, exporting causal tools as factor inputs, and remaining first-batch
entries; and the growth plan. The 480-entry
catalogue (ALPHA has 149, has part of 103, lacks 228) is the backlog but is not yet in the repository; random-exit
control remains among its highest-value gaps.

## Finding checks and recording the plan

`alpha tool find "<plain words>"` ranks checks by plain token overlap with each entry's `answers`, `situations` and
name, plus a small synonym table (`toolbox/find.py`). It uses no model and no network. Each hit shows what it answers,
its cost, the command to run it and the named set that holds it. `alpha tool situations` lists situation to checks,
cheapest first; the same table is pasted into [research/tools/toolbox-by-situation.md](../../../research/tools/toolbox-by-situation.md)
and a test keeps it equal to the registry. The closed list of situations lives only in `toolbox/situations.py`.

A check gives a reading in context, never a pass or fail, and any check may run at any time, also on one part of an idea.
Nothing gates a result. The guard against result-shopping is the record and the counts.

`alpha tool declare <run_id> --set <name> | --tools a,b,c [--why "..."]` appends one line with the time to
`ledger/declarations/<run_id>.jsonl`, before results. The runner is the one place a result is written. It marks the result
`declared` if a declaration naming the check (or its set) is older than the write, else `exploratory`. The word is in the
result's `labels`. `alpha tool results <run_id>` and `alpha results show` print it with the counts:
"N checks run on this result: D declared, E exploratory". Results stored before this change count as exploratory.
The `rdagent-post-judge` set runs by a fixed rule in code, so that code writes its declaration (`why`: "fixed set run by rule")
before the checks run: its results are `declared`. A stored result keeps the label it was written with; a later declaration
does not relabel it. Equal times count as exploratory. `alpha tool find` points "out of sample" to `alpha test` and "data doubt"
to `alpha data health`, because no toolbox check answers them yet.
Exploratory is a label, not an error, and no statistic, seed or result value depends on it.
