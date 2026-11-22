# Report: toolbox family K and L (risk, sizing, attribution)

Thirteen checks are built (`risk.worst_windows` was removed in review: it repeats `performance.worst_windows`). Fail-first: before the module existed, `tests/unit/test_toolbox_risk_sizing.py`
stopped at collection with `ModuleNotFoundError: alpha_cli.toolbox.families.risk_sizing`.

| Check id | Catalogue row | Known-answer source |
|---|---|---|
| `risk.parametric_var` | L2 | Hand formula -(mean + z sd) with scipy `norm.ppf`; scipy `t.fit` for the Student-t fit |
| `risk.cornish_fisher_var` | L3 | Zangari 1996 / Favre-Galeano 2002 polynomial, scipy skew and kurtosis |
| `risk.tail_fit` | L5 | Hill by hand on a geometric tail ((k+1)/2 ln 1.2); scipy `genpareto.fit`; McNeil-Frey formulas |
| `risk.var_coverage` | L6 | Kupiec 1995 by `math.log` on a series with 3 planted breaches |
| `risk.var_independence` | L7 | Christoffersen 1998 by `math.log` from hand-counted transitions |
| `risk.kelly` | L9 | Trades +0.2/-0.1 half and half: p-q/b = 0.25; growth stake 2.5 solved by hand |
| `risk.fractional_kelly` | L10 | Same trades: growth and drawdown at 2.5, 1.25, 0.625 by hand |
| `risk.optimal_f` | L11 | Same trades: f = 0.25 by hand (Vince 1990) |
| `risk.vol_target` | L12 | Alternating +-1% returns: constant weight from the formula |
| `risk.loss_streaks` | L18 | Brute force over all 2^10 trade orders |
| `attribution.hold_period` | K5 | Hand-counted buckets |
| `attribution.weekday` | K14 | Hand-counted weekdays; scipy `kruskal` |
| `attribution.drawdown_causes` | K17 | Hand-built equity and trades |

## Decisions

- Modules: `risk_sizing_a` to `_g` plus `risk_common.py`, because 300 lines was too small for one file. `risk_sizing.py` joins them into `CHECKS`.
  Tests: one file per source group would be many tiny files, so known answers sit in `test_toolbox_risk_sizing_{a,b,c,d}.py`
  and the shared too-little, repeat and future-input tests in `test_toolbox_risk_sizing.py`.
- Loss figures use the package `value_at_risk` where a historical figure is shown. The Kupiec and Christoffersen backtests use an expanding
  historical figure that sees only earlier bars (default 60 bars of history first).
- Vol target: a flat trailing window has no volatility, so the leverage cap applies to the next bar.
- Kelly uses each trade's `realized_return` (return on the amount used); the stake is in equity per trade.
- Edited outside my files (needed): `registry.py` (one import, one `*` entry); `tests/unit/test_toolbox_montecarlo_checks.py`
  (`== 16` became `>= 16`, since the registry now grows); the situations block in `research/tools/toolbox-by-situation.md`
  (a test requires it to equal the registry). The other builders touch the same block: expect a merge conflict; regenerate it with
  `alpha tool situations --markdown`.
- Readings use words, not digits, for fixed numbers (the citation check flags untagged numbers).

## Skipped rows

- K1, K8, K9, K12, K16 (market regression family): need a benchmark; `market.attribution` covers K1. K2, K11 need factors (F/X).
- K3 (one asset per run), K6 (trades carry no entry reason), K10 (no weights), K4 and K7, K13, K15 (existing checks cover them).
- L1, L4, L8, L19, L20 already exist; L13 CPPI, L14 margin stress, L16, L25 (need to re-run the engine or bars with other rules);
  L15 partial elsewhere; L17 overlaps `risk.optimal_f`; L22, L23 need positions or several series; L24 needs volume;
  L26 needs the drift-case Magdon-Ismail and Atiya function, not built to keep the limit of 14.
