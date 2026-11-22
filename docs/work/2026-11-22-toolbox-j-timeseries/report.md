# Report: toolbox family J, time-series checks

12 checks built in `apps/alpha-cli/src/alpha_cli/toolbox/families/timeseries_{a,b,c,d}.py` (joined as `CHECKS` in `timeseries.py`,
shared helpers in `timeseries_common.py`). All read the stored equity returns. Registered with one import and one `*TIMESERIES_CHECKS` line.
Tests: `tests/unit/test_toolbox_timeseries.py` (61 tests). Fail-first: before the modules existed, the file failed at collection (ImportError).

| Check id | Catalogue row | Known-answer source |
|---|---|---|
| timeseries.ljung_box | J5 * | statsmodels `acorr_ljungbox` |
| timeseries.autocorrelation | J6 | statsmodels `acf` and `pacf` (ldb); hand case for alternating series |
| timeseries.variance_ratio | J7 * | calls `alpha_patterns.cycles.variance_ratio`; trend/zigzag direction cases |
| timeseries.hurst | J8 * | calls `hurst_exponent` and `hurst_random_walk_reference` |
| timeseries.up_down_runs | J9 | calls `trade_runs_test`; hand-counted 10-sign case |
| timeseries.arch_lm | J10 | statsmodels `het_arch` on demeaned returns |
| timeseries.normality | J12 | scipy `jarque_bera`, `skew`, `kurtosis`, `shapiro` |
| timeseries.dfa | J23 | hand case F(4)=sqrt(0.2); white noise 0.5 (±0.08), its running sum 1.5 (±0.15) |
| timeseries.long_memory | J26 | explicit-DFT reference of the GPH regression |
| timeseries.sample_entropy | J21 | literal brute-force definition |
| timeseries.compressibility | J22 | Lempel-Ziv hand parses (6, 3, 2 parts) |
| timeseries.permutation_entropy | J16 | independent argsort count; monotone gives 0 |

## Decisions
- Time-series tests of the equity level are not built on prices; every check reads returns (the stored walk-forward equity). Unit-root tests
  of returns are trivial, so J1-J4 are skipped.
- `arch_lm` demeans the returns first (Engle's residuals of a constant-mean model). statsmodels `het_arch` does not; the test demeans for it.
- `normality` gives Shapiro-Wilk only up to 5,000 returns; above that it is unavailable with a reason.
- `hurst` is seeded: the white-noise comparison uses a seed from the contract's generator.
- Too little data: a result with every value unavailable and a reason that names the needed and the actual count.
- Tool card `research/tools/toolbox-timeseries.md` has a placeholder `verified` hash; `fs.py verify` was not run, as the brief says.
  `research/tools/README.md` was not edited (not in the brief).

- Exceptions to the common brief, needed for a green CI: (1) each check names existing situation tags (the find test requires one); the
  generated block in `research/tools/toolbox-by-situation.md` is regenerated for them; (2) `test_toolbox_montecarlo_checks.py` asserted
  exactly 16 listed checks; the number is dropped and the test compares the list with the registry. Other builders' branches will touch
  the same block and line: merge with `git merge origin/main` and regenerate the block.

## Skipped rows
- J1-J4 (unit-root tests): trivially rejected on returns; need price levels and MacKinnon tables not in numpy/scipy.
- J11 GARCH: needs an optimiser fit; not built to keep to numpy/scipy and the line limit.
- J13, J14, J30, J31: need two or more series (B x2, multi, R x2). J19: needs an event list. J32: needs a factor panel.
- J33: needs regime labels from a second input. J25 (BDS), J27, J28, J29: not built; at least 10 were reached with the starred and simpler rows.
- J17, J18, J20, J24: library functions exist but were left out to stay within 14 checks and the time budget.
