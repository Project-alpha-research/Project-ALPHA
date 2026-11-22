# Brief: toolbox checks, family I. Regime and conditional analysis

Branch: `feat/toolbox-i-regimes`. Module: `apps/alpha-cli/src/alpha_cli/toolbox/families/regimes.py`. Tests: `tests/unit/test_toolbox_regimes.py`.
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

## I. Regime and conditional analysis (28)

| # | Test | Question | Needs | Kind | Reference | ALPHA |
|---|---|---|---|---|---|---|
| I1 | Bull/bear split | Does it work in both up and down markets? | R + market | D | | partial |
| I2 | Volatility-regime split * | Does it work in calm and turbulent markets? | R + market | D | | have |
| I3 | HMM regimes | What hidden market states exist, and how does it do in each? | R | D | Hamilton 1989 (related) | have |
| I4 | Causal (past-only) HMM refit | Same, without looking ahead | R | D | | missing |
| I5 | Change-point detection (penalised/PELT) | When did return behaviour change? | R | D | Killick et al. 2012 | have |
| I6 | Online change points (BOCPD) | Detect a change as it happens | R | D | Adams & MacKay 2007 | missing |
| I7 | Chow test | Did the relationship break at a known date? | R | G | Chow 1960 | missing |
| I8 | CUSUM / CUSUM-of-squares test | Has the mean or variance drifted? | R | G | Brown, Durbin, Evans 1975 | missing |
| I9 | Bai-Perron multiple breaks | How many structural breaks, and where? | R | G | Bai & Perron 1998 | missing |
| I10 | Quandt-Andrews sup-F | Is there a break at an unknown date? | R | G | Andrews 1993 | missing |
| I11 | Day-of-week seasonality | Do some weekdays earn more? | R | D | | have·code |
| I12 | Month-of-year / turn-of-month | Do calendar months or month turns matter? | R | D | | missing |
| I13 | Session / hour-of-day profile | Which intraday sessions carry the edge? | intraday B | D | | missing |
| I14 | Event conditioning (FOMC, CPI, earnings, expiry) | Does the edge depend on scheduled events? | R + calendar | D | | missing |
| I15 | Macro conditioning (rates, curve, VIX, credit) | Does the edge depend on the macro backdrop? | R + X | D | | partial |
| I16 | Year-by-year returns * | Does it work in most years or only a few? | R | D | | have |
| I17 | Conditional lift tables with FDR | Which conditions change the hit rate, after multiple-test control? | E | G | | have |
| I18 | Market-state conditioning | Behaviour by derived market state | R + B | D | | have·code |
| I19 | Sub-period stability * | Do early and late halves agree? | R | G | | have·code |
| I20 | Drawdown-with-market check | Was the worst drawdown the market's doing? | RUN | D | | have |
| I21 | Regime-conditional performance table | Sharpe and return per regime | R | D | | have |
| I22 | Trend/range classification (ADX, efficiency ratio) | Does it work in trends, ranges, or both? | B | D | Kaufman | partial |
| I23 | Volatility-clustering regime (GARCH state) | Does it depend on current vol level? | R | D | Engle 1982; Bollerslev 1986 | missing |
| I24 | Markov-switching regression | Do coefficients differ by hidden state? | R | D | Hamilton 1989 | missing |
| I25 | Correlation-regime analysis (stock-bond, crisis correlation) | Do correlations break when it matters? | R multi | D | | missing |
| I26 | Liquidity-regime analysis | Does it fail when liquidity dries up? | B + volume | D | | missing |
| I27 | Holiday / Halloween / pre-holiday effects | Are named calendar effects present? | R | D | Bouman & Jacobsen 2002 (Halloween) | missing |
| I28 | Asymmetric beta (up-day vs down-day) | Is market exposure larger on down days? | R + market | D | | missing |

