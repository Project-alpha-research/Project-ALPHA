# Report: fourth-sweep polish (M134)

Each item: cause, change, test. Synthetic fixtures only. No real-data numbers.

Decisions
- The commit trailer names the model that did the work (the run's own attribution line), not the
  line quoted in the common rules. The pull request is ready, not draft, as this run's task says.
- A stored sentence stays as stored. Item 7 is fixed on the way out (`emit`), not in the stored text,
  because the setup-study digest test pins those bytes.

MEDIUM
1. Estimates. Cause: fixed constants (`alpha test` 240 s per asset; ML 1 s per asset-fold) and a
   `--paths` tip that scaled the whole run by 4. Change: new `_estimate.py` (`UnitTimer`, kept rate
   per computer). `alpha test` shows a rate kept from the last test, or says none exists; it
   measures the first asset and states the estimate again once. `alpha ml run` uses the rate kept
   from the last run; with none it says so and makes up no number. Kronos: `_forecast.Calibration`
   prices any run from the one warm-up; the tip uses the same batched formula. Tests:
   `test_estimate_clock.py`, `test_ml_progress_words.py`, `test_forecast_calibrated_estimate.py`
   (stubbed clock). NOT DONE: "first fold's time x folds left, restated after fold 2" for ML. The
   worker is a protected path and prints nothing per fold, so no fold time can be seen. The estimate
   is the kept rate of the last run. Within 30% on a busy desktop CPU was not measured (no such host).
   `alpha test` counts assets, not assets x variants x folds: the timed asset already includes them.
2. ML progress froze on the last fold. Cause: the fold count was capped at the estimate. Change: past
   the estimate the line says "in the last fold, or in the closing stages (scoring, writing the
   run)"; a second heartbeat names the scoring stage. Test: `test_ml_progress_words.py`.
3. Three cost figures. Finding: all three are right and measure different things. Before costs in
   `alpha report` and `cost_sweep.return_x0`: compounded return. `costs.break_even.cost_share`:
   share of summed per-bar gross profit, each bar weighted by the account size at its start.
   Change: each output says so. Test: hand computation in `test_toolbox_run_level_checks.py`
   (21% vs 16.64% compounded; share 0.2).
4. Results list. Cause: tool rows were listed with the rule-test word. Change: hidden unless
   `--tools`; a tool row reads "tool reading". Test: `test_spine_results_cmds.py`, `test_spine_tools.py`.
5. `alpha-web --help` started the server. Change: prints help and exits; card updated. Test: `test_web_help.py`.
6. ML missing symbols. Change: `_require_stored` names all, with the pull line each; card says the
   alternative. Test: `test_ml_missing_symbols.py`.
7. `uv run alpha`. Change: JSON and text output print `alpha`; stored text unchanged. Test: `test_m126_wording.py`.

LOW
8. Tries paragraph is shorter; "What decided it" heads every reading. 9. Date `YYYY-MM-DD HH:MM`; header
   "flags (count)". 10. Cause: the one-bar-later figure is re-computed by the quick check; said in a
   sentence. 11. `alpha tool run` text: four digits, money with `$`, label meanings, "the model".
12. `alpha figures list <run>`; `render` also writes `<figure>.<format>` beside the cache entry
   (JSON `path` is that name, `cache_path` the hashed one). 13. Folds from 1; plain names for engine
   names in subtitles; fan axis is dates when the run stored them. 14. Few paths: a count, "too few
   to rank", and the window. 15. Plain errors (options derived, crypto-data coverage); coverage says
   why "out of date"; `update --dry-run` says a pull re-pulls the whole series (it does). 16. Ledger
   summary headline counts ML and RD-Agent tries. 17. Minus before `$`; futures-preset sentence on
   a fresh stock or ETF run (not for `--from-run`). 18. `trade_pnl` axis says the account size.

Not fixed or partial: the ML fold-time estimate (item 1); the futures-preset sentence for `--from-run`
(item 17); item 15 "out of date" compares the report with the stored bars, with today's date beside
the newest bar, not with the newest closed session (no calendar at that point).

Review round (one round, synthetic data only)
- `alpha test` stopped with "start the timer before a unit finishes" when the first asset could
  not be read (high). The clock now starts at the first asset tested. Test: `test_estimate_clock.py`.
- An exact repeat (read from the stored run in a moment) saved its time as the rate, so the next
  real test was given a time of a second or so (medium). Only a run that tested every asset keeps
  its rate now.
- One kept rate served every rule: an owner rule with nine nearby settings was given the time of
  a built-in rule (medium; the brief's own case). Each rule kind keeps its own rate (with quick and
  no-diagnose apart). With two assets the measured estimate was never re-stated; it is now.
- Kronos: the formula said a batch of 32 paths costs what 8 cost, and it timed only steps one and
  two (medium). On a desktop CPU 32 paths take about four times 8, and a step costs more as the
  window grows, so a long run and the "--paths 32" tip were far too low. A batch now costs by its
  paths, and the warm-up times up to a quarter of the horizon (at most 64 steps).
  Test: `test_forecast_calibrated_estimate.py`.
- Item 3: the report's return before costs and the cost sweep's no-cost return are NOT the same
  figure. The report compounds the model's target weights on open-to-open moves (the plan). The
  sweep compounds the account's own fills with the costs added back. Both are right; each now
  says its basis. Test: `test_ml_run_tools.py` (the two bases differ on the fake-worker run).
- The ML progress test depended on machine speed; it now uses a kept rate that cannot be passed.
- Two smoke tests failed on the branch: the rule-test smoke compared the printed health
  sentence (now `alpha ...`) with the stored one (`uv run alpha ...`), and the tools smoke counted
  tool rows in the default list. Both tests now say the new behaviour: the printed text drops
  `uv run`, and tool rows show with `--tools` only.
- `figures render` pointed `path` at the plain copy, which had no explanation file beside it, so
  a reader of `path` lost the figure's text. The plain copy now has `<figure>.json` beside it.
