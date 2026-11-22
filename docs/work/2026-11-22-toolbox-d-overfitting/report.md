# Report: toolbox family D, overfitting and multiple-testing controls

Eleven new checks in `overfit_controls*.py`. All read the stored run's scored returns (or closed trades). All are readings, none seeded.
Tests: `tests/unit/test_toolbox_overfit_controls.py` (known answer, too little data, repeat, future-date rejection). The gate passes.

| Check id | Catalogue row | Known-answer source |
|---|---|---|
| `overfit_controls.probabilistic_sharpe` | D1 | Bailey and Lopez de Prado 2012 formula restated with scipy; equals `probabilistic_sharpe_ratio` |
| `overfit_controls.min_track_record` | D3 | Bailey and Lopez de Prado 2012 MinTRL formula restated with scipy |
| `overfit_controls.haircut_sharpe` | D13 | Harvey and Liu 2015, Bonferroni haircut, restated with scipy; a case where the adjusted p-value is 1 |
| `overfit_controls.min_backtest_length` | D14 | Bailey et al. 2014 bound 2 ln N / SR^2; hand answer 2 ln 100 years at Sharpe 1 |
| `overfit_controls.noise_best_sharpe` | D15 | `expected_max_sharpe` (library call) and the closed form with scipy |
| `overfit_controls.deflated_at_tries` | D2 at a stated count | PSR against the noise benchmark, restated with scipy |
| `overfit_controls.t_stat_hurdle` | D21 | Harvey, Liu and Zhu 2016; two-sided normal p of t = 3 is 0.0026997960632601866 |
| `overfit_controls.trade_count` | D22 | statsmodels `proportion_confint(method="wilson")` |
| `overfit_controls.required_history` | D23 | `required_observations_known_sigma` (library call) and the closed form with scipy |
| `overfit_controls.sequential_test` | D25 | Wald 1945 limits (hand values 2.7726 and -1.5581); log-likelihood ratio restated with numpy |
| `overfit_controls.shrunk_sharpe` | D26 | Normal-normal update with Lo 2002 standard error, restated |

## Decisions
- `n_trials` is a setting on the four try-count checks. 0 means the count recorded in the run manifest (`dsr.n_trials`); with none recorded the check says so.
- `min_backtest_length` takes `target_sharpe` 0 to mean the run's own Sharpe ratio.
- `haircut_sharpe` does the Bonferroni haircut of one p-value. A Sharpe ratio of zero or below has no haircut (reason given).
- `deflated_at_tries` is built although `overfit.deflated_sharpe` exists: that one uses only the ledger's recorded family; this one answers "what if N tries".
- Each check needs at least 30 scored bars; fewer gives the count and a reason, never a number.
- Wording of equation numbers in docstrings and caveats was written from memory without internet access; check them against the papers.
- Tests were written before the code, but I did not keep a failing run against missing code. The first run failed at collection on an import bug, then went green.
- `situations` of each check use existing tags, so the generated block in `research/tools/toolbox-by-situation.md` changed; I regenerated it. Other builders will need to regenerate it on merge.
- `tests/unit/test_toolbox_montecarlo_checks.py` asserted exactly 16 checks; I removed the fixed `16` (the list still equals the registry).

## Skipped
- D4, D5, D6, D7, D17, D20: need several strategies or a trial set (MS).
- D8 to D12: need a list of p-values the loader does not give.
- D16, D24: already built (ledger, frozen spec).
- D18: needs bars and parameters (B) and already exists as the in-sample permutation test.
- D19: out-of-sample degradation is already reported by `alpha test`.
