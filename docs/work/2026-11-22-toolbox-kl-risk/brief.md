# Brief: toolbox checks, family K. Attribution and exposure, and L. Risk and sizing

Branch: `feat/toolbox-kl-risk`. Module: `apps/alpha-cli/src/alpha_cli/toolbox/families/risk_sizing.py`. Tests: `tests/unit/test_toolbox_risk_sizing.py`.
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

## K. Attribution and exposure (17)

| # | Test | Question | Needs | Kind | Reference | ALPHA |
|---|---|---|---|---|---|---|
| K1 | Market beta and alpha regression (HAC) * | How much is just the market? | R + market | D | | have |
| K2 | Multi-factor regression (FF, Carhart, momentum) | What do known factors explain? | R + factors | D | Fama & French 1993; Carhart 1997 | missing |
| K3 | Contribution by asset / sector | Which names or sectors made the money? | T/R by asset | D | | partial |
| K4 | Long vs short contribution * | Which side earned the return? | T | D | | missing |
| K5 | Performance by holding period | Do short or long holds earn more? | T | D | | partial |
| K6 | Performance by entry reason / setup type | Which entry reason works? | T | D | | partial |
| K7 | Profit concentration | See C32 | T | D | | have |
| K8 | Market-neutral (beta-hedged) return | What is left after hedging the market? | R + market | D | | missing |
| K9 | Rolling beta | Does market exposure drift? | R + market | D | | missing |
| K10 | Brinson-style attribution | Allocation vs selection effect? | weights | D | Brinson, Hood, Beebower 1986 | missing |
| K11 | Style-tilt exposure (momentum, value, volatility, size) | What style is the strategy secretly? | R + factors | D | | missing |
| K12 | Correlation to benchmark | How correlated to the index? | R + benchmark | D | | partial |
| K13 | Top-N trade contribution | How much do the best N trades add? | T | D | | have |
| K14 | Weekday / time-of-day contribution | When does profit arise? | T | D | | partial |
| K15 | Exposure over time (gross/net) | How invested was it over time? | RUN | D | | have |
| K16 | Idiosyncratic vs systematic variance split | How much risk is market versus own? | R + market | D | | missing |
| K17 | Drawdown attribution | What caused the worst drawdown? | RUN | D | | partial |

## L. Risk and sizing (26)

| # | Test | Question | Needs | Kind | Reference | ALPHA |
|---|---|---|---|---|---|---|
| L1 | Historical VaR | Loss exceeded x% of the time | R | D | | have |
| L2 | Parametric (normal / t) VaR | VaR assuming a distribution | R | D | JP Morgan RiskMetrics 1996 | missing |
| L3 | Cornish-Fisher VaR | VaR adjusted for skew and kurtosis | R | D | | missing |
| L4 | Expected shortfall (CVaR) | Average loss beyond VaR | R | D | Artzner et al. 1999 | have |
| L5 | EVT tail fit (POT/GPD, Hill) | How heavy is the tail really? | R | D | McNeil & Frey 2000 | missing |
| L6 | Kupiec VaR backtest | Are VaR breaches at the stated rate? | R + VaR | G | Kupiec 1995 | missing |
| L7 | Christoffersen conditional coverage | Are breaches independent and at the right rate? | R + VaR | G | Christoffersen 1998 | missing |
| L8 | Risk of ruin * | Chance of hitting a fatal drawdown | R/T | D | | have |
| L9 | Kelly criterion * | What bet size maximises long-run growth? | T/R | D | Kelly 1956 | missing |
| L10 | Fractional Kelly | Safer fraction of Kelly | T/R | D | Thorp 1969 | missing |
| L11 | Optimal f | Fixed fraction maximising terminal wealth from past trades | T | D | Vince 1990 | missing |
| L12 | Volatility targeting | Does scaling to constant volatility help? | R | D | | missing |
| L13 | Drawdown-based sizing / CPPI | Does cutting size in drawdown help? | R | D | Perold 1986 | missing |
| L14 | Margin and leverage stress | What happens to a margin call under shocks? | R/T | D | | missing |
| L15 | Prop-firm rule simulation | Would it pass drawdown and target rules? | R | G | | partial |
| L16 | Stop-loss / drawdown-limit study | Does a hard limit improve or hurt? | T/B | D | | missing |
| L17 | Fixed-fraction position-size sweep | How do return and risk change with size? | T | D | | missing |
| L18 | Loss-streak probability | How long a losing streak should we expect? | T | D | | partial |
| L19 | Drawdown percentile distribution * | What drawdown to expect at the 95th percentile? | R | D | | have |
| L20 | Stress-scenario table | Loss under named shocks | R | D | | have |
| L21 | Worst day/week/month | Worst realised windows | R | D | | missing |
| L22 | Risk contribution by position | Which position drives portfolio risk? | positions | D | | missing |
| L23 | Correlations-go-to-one stress | Loss if diversification vanishes | R multi | D | | missing |
| L24 | Liquidity-adjusted VaR | VaR including cost to exit | R + volume | D | Bangia et al. 1999 | missing |
| L25 | Exit-rule comparison (trailing stop, time stop, target) | Which exit rule is best? | T + B | D | | partial |
| L26 | Expected max-drawdown formula | Expected drawdown for a given Sharpe and horizon | R | D | Magdon-Ismail & Atiya 2004 | missing |

