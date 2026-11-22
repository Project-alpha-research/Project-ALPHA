# Brief: toolbox checks, family E. Resampling and Monte Carlo

Branch: `feat/toolbox-e-resampling`. Module: `apps/alpha-cli/src/alpha_cli/toolbox/families/resampling_more.py`. Tests: `tests/unit/test_toolbox_resampling_more.py`.
Rules: `docs/work/2026-11-22-toolbox-common/brief.md` (read it fully first).

Build at least 10 and at most 14 new checks from this family of the catalogue. The table below is the catalogue section, copied as
research notes: its "ALPHA" column was a reading of the code on 2026-11-18 and may be out of date; check what exists before you build.

Legend:
## Legend

- **Needs:**
  - T = trades
  - R = return or equity series
  - B = price bars
  - F = factor or signal panel (date x asset, plus forward returns)
  - MS = multiple strategies or a trial set
  - ML = model or predictions
  - E = event list
  - X = extra data (macro, calendar, fundamentals, funding)
  - RUN = a finished alpha run
- **Kind:** D = diagnostic (describes), G = pass/fail test, C = control or baseline.
- **ALPHA:** have / partial / missing. Suffixes: ·code means a library function with no `alpha` command; ·dev means developer tests only.
- **Stars:** * marks the ones that matter most for a daily-bar swing trader with small size (43 in total).

---

## E. Resampling and Monte Carlo (36)

| # | Test | Question | Needs | Kind | Reference | ALPHA |
|---|---|---|---|---|---|---|
| E1 | Trade-order reshuffle | How much does the drawdown depend on trade order? | T | D | | partial |
| E2 | iid bootstrap of returns | What range of outcomes under independent returns? | R | D | Efron 1979 | have |
| E3 | Stationary bootstrap * | Same, preserving serial dependence | R | D | Politis & Romano 1994 | have |
| E4 | Moving block bootstrap | Same, with fixed blocks | R | D | Künsch 1989 | have |
| E5 | Circular block bootstrap | Same, without end effects | R | D | Politis & Romano 1992 | missing |
| E6 | BCa confidence interval | Bias-corrected CI for a statistic | R | D | Efron 1987 | have |
| E7 | Regime-switching path simulation | What if calm and turbulent regimes recur differently? | R | D | | have |
| E8 | Student-t path simulation | Paths with fat tails | R | D | | have |
| E9 | GARCH path simulation | Paths with volatility clustering | R/B | D | | have |
| E10 | Randomised-price null * | Does the rule beat the same rule on structureless prices? | B + rule | G | | have |
| E11 | Bar permutation (OHLC, gaps and intrabar shapes) | Does the rule beat the same data with order scrambled? | B + rule | G | Masters; neurotrader888 ...
| E12 | In-sample MCPT | See D18 (selection-bias version) | B + params | G | Aronson 2006 | have |
| E13 | Signal permutation (shuffle signal vs returns) | Does the pairing of signal to return matter? | F/R | G | | missing |
| E14 | Return shuffle (destroy autocorrelation) | Is the edge from return order? | R | C | | partial |
| E15 | Random-entry control * | Do random entries with same exits do as well? | B + T | C | | have |
| E16 | Random-exit control * | Do our entries with random exits do as well? | B + T | C | | missing |
| E17 | Inverted-signal control * | Does the opposite signal do equally well (just the market)? | RUN | C | | have |
| E18 | Price-noise injection | Does a small data wobble change the answer? | B | D | | have |
| E19 | Timing and fill perturbation | Does a one-bar shift or jittered fill change it? | B | D | | partial |
| E20 | Start-date sensitivity * | Does the result depend on when we begin? | B + rule | D | | missing |
| E21 | End-date sensitivity | Does it depend on where we stop? | B + rule | D | | missing |
| E22 | Subsample consistency (interleaved) | Do random halves agree? | R | D | | partial |
| E23 | Leave-one-trade-out jackknife | Does any single trade drive the result? | T | D | Quenouille 1949; Tukey 1958 | missing |
| E24 | Leave-one-year-out | Does any single year drive the result? | R | D | | missing |
| E25 | Leave-one-asset-out | Does any single asset drive the result? | R by asset | D | | missing |
| E26 | Wild bootstrap | Bootstrap robust to heteroskedasticity | R | D | Wu 1986; Liu 1988 | missing |
| E27 | Sequential bootstrap (uniqueness-aware) | Bootstrap respecting overlapping labels | events | D | López de Prado 2018 | have·code |
| E28 | Generative-model synthetic paths (Kronos) | How does it do on model-generated futures? | B + model | D | | partial |
| E29 | Phase-randomised / IAAFT surrogates | Does the edge need nonlinear structure? | B | C | Theiler 1992; Schreiber & Schmitz 1996 | missing |
| E30 | Parametric (GBM) price null | Same null with a simple random-walk model | B | C | | have |
| E31 | Stress shocks (vol scaling, one-off shocks) | What if volatility is higher or a shock hits? | R | D | | have |
| E32 | Historical scenario replay (2008, 2020, 2022) | How would it have done in known crises? | B | D | | missing |
| E33 | Calendar-block permutation (years/months) | Is the edge tied to particular periods? | B | C | | missing |
| E34 | Cross-sectional label shuffle within date | Does asset identity matter, or just timing? | F | C | | missing |
| E35 | Resampled efficiency | How stable are optimiser weights across resamples? | R matrix | D | Michaud 1998 | missing |
| E36 | Monte-Carlo risk of ruin | Chance of hitting a ruin drawdown | R | D | | have |

