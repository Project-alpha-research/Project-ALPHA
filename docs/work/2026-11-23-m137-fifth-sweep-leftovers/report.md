# Report: fifth sweep leftovers

Decisions and results per item. No numbers from a real run are written here.

## 1. `alpha results` list shows ML, forecast, forecast-eval and Monte Carlo runs
- Cause: the list reads only the trial ledger. An ML row stores "recorded without a reading"; forecast and Monte Carlo runs write no ledger row.
- Change: `results_other_runs.py`. An ML row takes its word and Sharpe from `ml_reading` (the source `alpha report` uses). Forecast, forecast-eval and Monte Carlo runs are read from their run folders. A folder run keeps no time, so its list time is the time its manifest file was written.
- Test: `tests/unit/test_results_list_other_runs.py` (failed first: only the ML run was listed).
