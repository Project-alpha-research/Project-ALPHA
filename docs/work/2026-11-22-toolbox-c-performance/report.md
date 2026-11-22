# Report: toolbox family C, performance statistics

Branch `feat/toolbox-c-performance`. Twelve new checks, all `performance.*`, all instant, all run on stored files of a finished run.

## Checks built

| Check id | Catalogue row | Known-answer source (`tests/unit/test_toolbox_performance_stats.py`) |
|---|---|---|
| `performance.ulcer` | C8 ulcer index, C9 Martin ratio | Hand: one 10% drawdown over 31 points gives sqrt(5 x 0.1^2 / 31). Martin and McCann 1989. |
| `performance.pain` | C39 pain index and ratio | Hand: 5 x 0.1 / 31. Zephyr pain index. |
| `performance.sterling_burke` | C40 Sterling and Burke | Hand: one and two drawdown episodes (0.1; 0.1 and 0.2), `top=1` cap. Burke 1994. |
| `performance.recovery_factor` | C44 recovery factor | Hand: profit 10, worst drop 10, factor 1. |
| `performance.gain_to_pain` | C16 gain-to-pain | Hand: 11/9. Schwager 2012. |
| `performance.kappa` | C41 kappa, upside potential | Hand for orders 1, 2, 3 (order 1 = Omega - 1); a second threshold. Kaplan and Knowles 2004. |
| `performance.lo_sharpe` | C36 autocorrelation-adjusted Sharpe | Lag-by-lag loop written in the test, on a seeded AR(1) series. Lo 2002. |
| `performance.cornish_fisher_sharpe` | C43 higher-moment Sharpe | `scipy.stats.skew` and `kurtosis`. Pezier and White 2008. |
| `performance.worst_windows` | C38 worst N-bar loss table | Hand: worst bar -10%, worst 5 bars -10%, worst 21 bars +10%. |
| `performance.payoff_expectancy` | C21 payoff ratio, C22 expectancy | Hand: 13 trades, 3.5 / (13/6), 8/13. |
| `performance.streaks` | C23 win/loss streaks | Hand: longest win 2, longest loss 3, 4 losing streaks. |
| `performance.holding_period` | C27 holding-period distribution | Hand: median 2, mean 41/13, winners 22/6, losers 3. |

Each check also has a too-little-data test (fewer than 20 returns or 10 trades gives "Too little to read" with the count) and a
repeat-is-identical test (two fresh homes, same bytes). Tests: 39 in the new file.
Fail-first evidence is NOT available: I wrote the check code before the tests (a process slip). The tests did fail first on
three real faults, which I then fixed: a NaN threshold reached the ledger (now a fixed list of values), a reading carried untagged
numbers (`worst_windows`), and the contract tests demanded situation tags.

## Rows skipped and why

- C1, C2, C3, C6, C7, C11, C12, C13, C14, C20, C24, C25, C26, C28, C29, C30, C32, C33, C35: already "have" or covered by `uv run alpha tool list`
  (`performance.downside_ratios` also covers C4 Sortino, C5 Calmar, C10 Omega, C15 tail ratio; `trades.concentration` covers C32 and C33).
- C17, C18, C19, C34, C42: need a benchmark return series (not part of the stored-equity input for these checks); other families own them.
- C31 MAE/MFE: needs bars and trade paths; not in the stored inputs.

## Decisions

1. **Expectancy in R multiples.** Stored trades carry no stop distance. One average losing trade stands in for R. The output name and gloss say so.
2. **Thresholds.** 20 stored returns and 10 closed trades are the minimum to read. Constants live in `performance_stats_common.py`.
3. **Modules.** `performance_stats.py` joins `_a` (ulcer, pain, Sterling and Burke), `_b` (gain-to-pain, kappa, Lo), `_c` (Cornish-Fisher, worst windows, recovery factor), `_d` (trades); a shared `_common`.
4. **Lo (2002).** The sum over lags is cut at `max_lag` (default 10, at most 60, and at bars-per-year minus one). Full Lo sums to q - 1.
   I could not check the equation number offline; the docstring and gloss name the eta(q) factor, not an equation number.
5. **Sterling.** Conventions differ. This check: yearly return over the mean depth of the `top` (default 5) deepest episodes.
6. **Kappa threshold** is a fixed list of allowed values: a free float lets "nan" reach the ledger.
7. **Situations.** Contract tests require at least one tag; I used only existing tags. This changes the generated block of
   `research/tools/toolbox-by-situation.md`; I regenerated it. Other builders will conflict there: regenerate with `alpha tool situations --markdown`.
8. **Existing test edited.** `test_toolbox_montecarlo_checks.py::test_listed_and_described` asserted exactly 16 tools; it now compares
   the list with `SPECS` (a count that moves with every family, not a weakened guard).
9. **Tool card** `research/tools/toolbox-performance-stats.md`: its `verified:` hash is a placeholder. The brief forbids `fs.py verify`, so it is listed as stale.
