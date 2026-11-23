# Report: fifth sweep leftovers

Decisions and results per item. No numbers from a real run are written here.

## 1. `alpha results` list shows ML, forecast, forecast-eval and Monte Carlo runs
- Cause: the list reads only the trial ledger. An ML row stores "recorded without a reading"; forecast and Monte Carlo runs write no ledger row.
- Change: `results_other_runs.py`. An ML row takes its word and Sharpe from `ml_reading` (the source `alpha report` uses). Forecast, forecast-eval and Monte Carlo runs are read from their run folders. A folder run keeps no time, so its list time is the time its manifest file was written.
- Test: `tests/unit/test_results_list_other_runs.py` (failed first: only the ML run was listed).

## 2. Monte Carlo with few paths
- Cause: the loss line and the P(loss), ruin and drawdown lines printed shares of paths whatever the path count.
- Change: under 20 paths every line gives a count ("Result: all 8 simulated paths ended with a loss; 8 paths is too few to rank"). The stored reading and the report lines use the same helper `path_count_words`. The older rank sentence keeps its own stricter 100-path limit.
- Test: `tests/unit/test_mc_few_paths_words.py` (failed first).

## 3. `alpha monte-carlo kronos` evaluation id
- Cause: `--forecast-eval-run` was required and its help did not say where the id comes from.
- Change: help and the missing-option message say "run `alpha forecast eval <SYMBOL>` first (a few minutes); it prints the id". If exactly one stored forecast-eval run has the source run's symbol and snapshot, it is used and the command says so. Zero or several fitting runs fail loud with the next step. To stay under the size ceiling of `kronos`, two blocks moved into `_resolve_eval` and `_horizon_steps` (no behaviour change).
- Test: `tests/unit/test_monte_carlo_cmds.py` (failed first).

## 4. `alpha test --recheck` progress
- Cause: `_recheck` called `recheck_idea` with no estimate and no heartbeat.
- Change: a shared `_start_progress` (estimate line, stage, clock) serves a normal test and a recheck; `recheck_idea` takes an optional `stage` callback. A recheck keeps no rate (it writes nothing).
- Test: `tests/unit/test_recheck_progress.py` (failed first).
