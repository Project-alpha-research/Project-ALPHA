---
owner: command line runs and validation
sources:
  - apps/alpha-cli/src/alpha_cli/toolbox/**/*.py
  - apps/alpha-cli/src/alpha_cli/tool_cmds.py
  - apps/alpha-cli/src/alpha_cli/_rdagent_checks.py
  - tests/unit/test_toolbox_*.py
verified: 94e1a94326724cbb
---

# Command line toolbox

Rules for the toolbox catalogue behind `alpha tool`: which checks are registered, how to add one and the honesty rules
for runs. The rules for follow-up tools on one rule test are in [cli-investigation-tools.md](cli-investigation-
tools.md). Why the toolbox exists: [toolbox](../project/components/toolbox.md).

## Adding a check

1. Write a `ToolSpec` (`toolbox/contract.py`) in a module under `toolbox/families/` (`costs`, `market`, `overfit`,
   `performance`, `resampling`, `robustness`, `trades`).
2. Add it to the explicit tuple `SPECS` in `toolbox/registry.py`. Nothing is found automatically. The fourteen
   registered ids: `market.attribution`, `market.vol_regimes`, `market.changepoints`, `performance.downside_ratios`,
   `robustness.start_end_dates`, `trades.side_contribution`, `trades.concentration`, `costs.break_even`,
   `resampling.sharpe_interval`, `resampling.return_interval`, `resampling.drawdown_distribution`,
   `trades.dependence`, `overfit.deflated_sharpe`, `resampling.block_bootstrap_paths`. Named sets and their execution
   order live in `toolbox/sets.py`.
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

Fourteen entries are registered. Three describe one recorded rule test. `market.attribution` measures exposure against
full-history buy and hold, including eligible cash dividends. `market.vol_regimes` compares calm and turbulent
markets. `market.changepoints` identifies when behaviour shifted. The named set `market-context` runs all three. Five
more read the run's stored walk-forward files instead of replaying it: `performance.downside_ratios` (Sortino, Calmar,
Omega, tail ratio beside the stored Sharpe), `robustness.start_end_dates` (25 windows with moved first and last dates,
against buy and hold), `trades.side_contribution` (long versus short), `trades.concentration` (profit without the best
trades) and `costs.break_even` (cost multiples at zero return and at buy and hold). Their
[card](../../../research/tools/run-level-checks.md) gives the definitions. Six tests use the same stored history. The
[resampling card](../../../research/tools/resampling-checks.md) covers Sharpe and compound yearly return intervals,
independent-return drawdowns, and block-bootstrap final returns and drops. `trades.dependence` tests the order of
closed-trade outcomes. `overfit.deflated_sharpe` reuses the verdict's family correction on the ledger count and prior
comparable Sharpes frozen in the run, and states that count. See the [family counting
card](../../../research/tools/deflated-sharpe-and-trials.md).

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

The RD-Agent checks replace no existing command, card or verdict. Later one-in-one-out candidates are the interval
lines in `alpha report`, the IID drawdown summary in `alpha monte-carlo classical`, the runs z-score shown by `alpha
figures render` and the family DSR reported by `alpha results cite`. Each command also serves other uses.

**Other work outstanding:** letting the agent name checks in its proposal before judging, showing checks in the
proposal discussion, and more input adapters. Other gaps include a reserved-period cut-off for rule-test inputs (today
they carry exposure labels), a Workstation and MCP listing, a generated catalogue, counting sweep variants in
deflation, a budget for agent-selected checks, exporting causal tools as factor inputs, and remaining first-batch
entries (minimum track record length waits for a function in `alpha_validation`); and the growth plan. The 480-entry
catalogue (ALPHA has 149, has part of 103, lacks 228) is the backlog but is not yet in the repository; random-exit
control remains among its highest-value gaps.
