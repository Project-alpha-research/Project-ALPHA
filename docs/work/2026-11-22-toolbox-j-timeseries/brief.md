# Brief: toolbox checks, family J. Time-series diagnostics

Branch: `feat/toolbox-j-timeseries`. Module: `apps/alpha-cli/src/alpha_cli/toolbox/families/timeseries.py`. Tests: `tests/unit/test_toolbox_timeseries.py`.
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

## J. Time-series diagnostics (33)

| # | Test | Question | Needs | Kind | Reference | ALPHA |
|---|---|---|---|---|---|---|
| J1 | ADF unit-root test | Does the series have a unit root? | B/R | G | Dickey & Fuller 1979 | missing |
| J2 | KPSS stationarity test | Is the series stationary? | B/R | G | Kwiatkowski et al. 1992 | missing |
| J3 | Phillips-Perron test | Unit root, robust to serial correlation | B/R | G | Phillips & Perron 1988 | missing |
| J4 | Zivot-Andrews test | Unit root with a structural break | B/R | G | Zivot & Andrews 1992 | missing |
| J5 | Ljung-Box test | Are returns serially correlated overall? | R | G | Ljung & Box 1978 | missing |
| J6 | ACF / PACF | At which lags is there correlation? | R | D | | have·code |
| J7 | Variance-ratio test | Do returns trend or mean-revert over k days? | R | G | Lo & MacKinlay 1988 | have·code |
| J8 | Hurst exponent | Trending, random or mean-reverting? | R | D | Hurst 1951 | have·code |
| J9 | Runs test | Are up/down sequences random? | R | G | Wald & Wolfowitz 1940 | have·code |
| J10 | ARCH-LM test | Is there volatility clustering? | R | G | Engle 1982 | missing |
| J11 | GARCH fit | What are volatility persistence and shock response? | R | D | Bollerslev 1986 | missing |
| J12 | Normality tests (Jarque-Bera, Shapiro-Wilk, Anderson-Darling, KS) | Are returns normal? | R | G | Jarque & Bera 1980 | missing |
| J13 | Engle-Granger cointegration | Do two prices share a long-run link? | B x2 | G | Engle & Granger 1987 | missing |
| J14 | Johansen cointegration | How many cointegrating links in a set? | B multi | G | Johansen 1991 | missing |
| J15 | Mean-reversion half-life (OU) | How fast does a spread revert? | B/R | D | | missing |
| J16 | Permutation entropy | How ordered is the price sequence? | B | D | Bandt & Pompe 2002 | have·code |
| J17 | Time-reversibility / asynchrony | Does the series look different run backwards? | B | D | | have·code |
| J18 | Visibility-graph metrics | What network structure does the series have? | B | D | Lacasa et al. 2008 | have·code |
| J19 | Hawkes process | Do shocks cluster and excite later shocks? | events | D | Hawkes 1971 | have·code |
| J20 | Dominant cycle (spectral) | Is there a repeating cycle length? | B | D | | have·code |
| J21 | Sample / approximate entropy | How irregular is the series? | B/R | D | Richman & Moorman 2000 | missing |
| J22 | Lempel-Ziv / compression complexity | How compressible (predictable) is it? | B/R | D | | missing |
| J23 | Detrended fluctuation analysis | Long-range correlation, robust to trends | R | D | Peng et al. 1994 | missing |
| J24 | Rolling Hurst / variance ratio | Does the character of the market drift? | B | D | | have·code |
| J25 | BDS test | Is there any nonlinear dependence? | R | G | Brock, Dechert, Scheinkman 1996 | missing |
| J26 | GPH long-memory estimator | Fractional integration order? | R | D | Geweke & Porter-Hudak 1983 | missing |
| J27 | Spectral / wavelet decomposition | Which time scales carry the variance? | R | D | | missing |
| J28 | Kalman / state-space trend-noise ratio | What share is trend vs noise? | B | D | | missing |
| J29 | Fractional differencing, d selection | How much differencing keeps memory but passes stationarity? | B | D | Hosking 1981; López de Prado 2018 | pa...
| J30 | Granger causality | Does one series help predict another? | R x2 | G | Granger 1969 | missing |
| J31 | Transfer entropy | Directed information flow, nonlinear | R x2 | D | Schreiber 2000 | missing |
| J32 | Mutual information (signal vs return) | Any nonlinear dependence of return on signal? | F | D | | missing |
| J33 | Two-sample KS (return distribution by regime) | Do distributions differ between states? | R | G | Kolmogorov; Smirnov | missing |

