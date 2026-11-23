# Report: third sweep, tools and engines (M127)

Fail-first: items 1–2 were run against the old code first (probe test: `equity_vs_passive` and `fold_sharpe`
listed available but not drawing; `costs.break_even` gave "made before costs were stored"; `regimes.bull_bear`
refused on the buy-and-hold value). Items 3, 5, 6, 7, 8 had tests that failed before the change.

1. **Figures of an ML run.** Cause: the replay stored no basket line and `fold_sharpe` read folds the manifest never held.
   Change: new ML runs store the equal-weight basket (kind `equal_weight_basket_...`); `fold_sharpe` reads `ml_periods.parquet`;
   a figure that cannot draw says why in one sentence; `figures export` ends in a plain message, not a traceback;
   `exposure_turnover` is now listed unavailable when the run stored neither. Old runs: "made before ... run `alpha ml run` again".
   Tests: `tests/integration/test_ml_run_tools.py`.
2. **Toolbox on an ML run.** Cause: no per-period costs, no basket line. Change: both stored for new runs (`HOLD_KINDS` gained the
   basket kind); refusals are one sentence with no mention of rule tests. One parametrised test runs every check on a synthetic ML run.
3. **ML reading.** Reading word from the rule-test words (always "not clear of chance" for a full run, "too little to read" under
   100 test days, because a model run holds no random-data test or interval); "The model returned less than holding the basket." as
   a sentence and a flag; every number glossed (`ml_glosses.py`); held-back bars per asset; chart titles say "20 assets · model run".
4. **`alpha ml run` progress.** The worker prints nothing, so the fold is estimated from time (labelled "about"). Default rate
   1 s per asset and fold on a first run; later runs use the measured rate. Decision: a default I could not measure here.
5. **Kronos estimates.** A timed warm-up (model load, then one full batch of paths for one step and for
   two steps) gives the time per step and the fixed time per batch; rounded up; the heartbeat says
   "taking longer than expected; still running". Review: on one real Kronos call on this desktop the
   estimate was within about 10% of the real time; the warm-up costs about 20 seconds.
6. **Monte Carlo Kronos.** Prints median end value with units, where the real run sits, and the window dates; `results show`
   and `report` read Monte Carlo runs; "Real run" is the one name; the regime-window note is plain.
7. **`forecast eval`.** Held-back wording; "N dates is too few to judge coverage" under 30 origins; model read offline
   when its files are cached. Decision: the Hugging Face warning is avoided by not asking the hub, not by a log filter.
8. **Small.** `alpha lookalike SPY` works. `--rdagent-ledger` on the `ledger` group is kept: it does something there (tests
   cover it). The summary headline adds "The RD-Agent ledger adds N trials (...)". `rdagent run --dry-run` works without the runtime.

Not fixed / notes: `tests/unit/test_reserved_date_one_home.py` and
`test_forecast_eval_fails_loud_when_nothing_fits` fail on main too (not touched). No code-size baseline changed.
Refusal hints and the Kronos "Expected time" line now include the warm-up load time once.
