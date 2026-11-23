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

## 5. `alpha ml run` fold progress
- Cause: the progress line guessed "about fold k of N" from elapsed time.
- Finding: the protected worker writes `predictions.parquet`, the ensemble file and `result.json` once, after all folds (`workers/qlib/.../real.py` `_publish` calls). It writes no per-fold file. So the CLI cannot count folds, and no fold is named.
- Change: the line now says "Model training: still running, N seconds so far, fold count N; this stage reports when it ends." The closing stage keeps its own line ("Scoring the model run and writing the run"). `fold_phrase` was removed as an orphan.
- Test: `tests/unit/test_ml_progress_words.py`.

## 6. `cost_realism.cost_sweep` on an ML run (and the scientific-notation half of item 10)
- Cause: `alpha tool run` printed a "fraction" unit as a bare fraction; and the no-cost figure (from the account's fills) had no basis sentence next to the report's figure (planned weights).
- Change: `_shown` prints a fraction as a percent. For a model run, `cost_sweep` adds "Return with no costs is from the account's fills with costs added back; `alpha report` uses the planned weights." Stored values are unchanged.
- Test: `tests/unit/test_tool_run_text.py`.

## 10b. `alpha tool run` scientific notation
- Cause: `:.4g` gives `1.5e-07` for tiny or large numbers.
- Change: `_plain` prints fixed digits instead. Test: same file (parametrised over units).

## 10a. The tries paragraph
- Cause: the last sentence ended "plus these: N." with no word for what N counts.
- Change: "The luck adjustment adds those nearby settings to the larger of the first two counts, which makes N tries in all." The two older tests that pinned the old ending now pin the new one.

## 11. `alpha data update --dry-run` note
- Cause: the "re-pulls every day" note was part of each symbol's line.
- Change: one line per symbol, then the note once at the end.
- Test: `tests/unit/test_data_update_cmds.py` (failed first, checked by stashing the change).

## 12. `alpha ledger summary` "By kind"
- Cause: the line printed only the rule-test kinds of the headline count; ML tries are counted apart ("Counting N ML tries").
- Change: the text line adds `ml_run` when there are ML tries. The JSON field `by_kind` is unchanged.
- Test: `tests/unit/test_ledger_cmds.py`.

## 13. `alpha ml run` missing-symbol lines
- Cause: the pull lines held `<date>` placeholders.
- Decision: an ML spec has no start date field (keys: name, assets, features, horizon_days, model, split). The start is the earliest first stored bar among the assets that are stored; with nothing stored, it is two calendar days per training, validation and test day of the spec's split. The end is today (UTC).
- Test: `tests/unit/test_ml_missing_symbols.py` (failed first).

## 8. `alpha diagnose` Sharpe differences
- Cause: "Price noise" and "Opposite rule" compare with a full-sample engine re-run of the rule (`document["full_sample"]`), while the headline is the out-of-sample Sharpe.
- Change: both lines say so in a half sentence, added when printing. The stored sentences are unchanged (a rule test's stored text is compared by `--recheck`).
- Test: `tests/unit/test_report_readings.py`.

## 9. Forecast picture names and the fan label
- Cause: `alpha forecast run` printed the cache path (`<figure>.<hash>.png`); the Kronos fan label was "Kronos synthetic OHLCV equity (x)".
- Change: `_cone_pictures` copies through the existing `_with_plain_name` (as `alpha figures` does), so the printed files are `forecast_fan.png` and `forecast_fan.annotated.png`. The Kronos fan label is "Account value on simulated prices (1 = start)" (`fan_axis_label`). The other families keep their labels.
- Test: `tests/unit/test_forecast_picture_names.py` (failed first).
