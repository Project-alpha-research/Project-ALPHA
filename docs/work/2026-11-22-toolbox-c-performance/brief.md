# Brief: toolbox checks, family C. Rule and strategy performance statistics

Branch: `feat/toolbox-c-performance`. Module: `apps/alpha-cli/src/alpha_cli/toolbox/families/performance_stats.py`. Tests: `tests/unit/test_toolbox_performance_stats.py`.
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

## C. Rule and strategy performance statistics (44)

| # | Test | Question | Needs | Kind | Reference | ALPHA |
|---|---|---|---|---|---|---|
| C1 | Total return and CAGR | What did it earn per year? | R | D | | have |
| C2 | Annualised volatility | How variable are the returns? | R | D | | have |
| C3 | Sharpe ratio * | What is the return per unit of risk? | R | D | Sharpe 1966/1994 | have |
| C4 | Sortino ratio | Return per unit of downside risk? | R | D | Sortino & Price 1994 | missing |
| C5 | Calmar ratio | Return per unit of worst drawdown? | R | D | Young 1991 | missing |
| C6 | Maximum drawdown * | What was the worst peak-to-trough fall? | R | D | | have |
| C7 | Drawdown episodes / time under water * | How deep and how long were the bad stretches? | R | D | | have |
| C8 | Ulcer index | How painful is the drawdown path, depth and duration? | R | D | Martin & McCann 1989 | partial |
| C9 | Martin (ulcer performance) ratio | Return per unit of ulcer? | R | D | Martin & McCann 1989 | partial |
| C10 | Omega ratio | Probability-weighted gains vs losses above a threshold? | R | D | Keating & Shadwick 2002 | missing |
| C11 | Profit factor * | Gross wins per unit of gross losses? | T | D | | have |
| C12 | Skewness and kurtosis | How asymmetric and fat-tailed are returns? | R | D | | have·code |
| C13 | Historical VaR | What loss is exceeded 5% of the time? | R | D | | have |
| C14 | Expected shortfall (CVaR) | What is the average loss beyond VaR? | R | D | | have |
| C15 | Tail ratio | Are right-tail gains bigger than left-tail losses? | R | D | | missing |
| C16 | Gain-to-pain ratio | Total return per unit of summed losses? | R | D | Schwager | missing |
| C17 | Information ratio / tracking error vs benchmark | Does it add return over the benchmark per unit of active risk? | R + benchmark | D | Grinold & Ka...
| C18 | Treynor ratio | Return per unit of beta? | R + benchmark | D | Treynor 1965 | missing |
| C19 | Jensen alpha and beta | What return is left after market exposure? | R + benchmark | D | Jensen 1968 | have |
| C20 | Win rate / hit rate | What share of trades won? | T | D | | have |
| C21 | Payoff ratio (average win / average loss) | Do winners outsize losers? | T | D | | partial |
| C22 | Expectancy (per trade, in R multiples) * | What is the average result per trade? | T | D | Tharp | partial |
| C23 | Win/loss streak distribution | How long can losing streaks get? | T | D | | partial |
| C24 | Longest recovery time | How long did the worst drawdown take to recover? | R | D | | have |
| C25 | Exposure / time in market | How much of the time was capital deployed? | RUN | D | | have |
| C26 | Turnover | How much was traded? | RUN | D | | have |
| C27 | Holding-period distribution | How long are trades held? | T | D | | partial |
| C28 | Monthly and yearly return table | What did each month and year do? | R | D | | have |
| C29 | Rolling Sharpe / volatility | Does risk-adjusted return drift over time? | R | D | | have |
| C30 | Return histogram and QQ plot | How do returns differ from normal? | R | D | | have |
| C31 | MAE/MFE (adverse and favourable excursion) | How far do trades go against or for us before closing? | T + B | D | Sweeney | partial |
| C32 | Profit concentration * | Is profit from a handful of trades? | T | D | | have |
| C33 | Remove best/worst N trades | What if the luckiest trades never happened? | T | D | | partial |
| C34 | Benchmark comparison (buy and hold) * | Did it beat just holding? | R + benchmark | C | | have |
| C35 | Bootstrap CI on Sharpe | What range is the Sharpe plausibly in? | R | D | | have |
| C36 | Autocorrelation-adjusted Sharpe | What is annualised Sharpe when returns are serially correlated? | R | D | Lo 2002 | missing |
| C37 | Sharpe-difference test | Is one Sharpe really higher than another? | R x2 | G | Jobson & Korkie 1981; Ledoit & Wolf 2008 | missing |
| C38 | Worst N-day / week / month loss table | What are the worst rolling-window outcomes? | R | D | | missing |
| C39 | Pain index and pain ratio | Average drawdown depth, and return per unit? | R | D | Zephyr | missing |
| C40 | Sterling and Burke ratios | Return per unit of average or squared drawdown? | R | D | | missing |
| C41 | Kappa and upside-potential ratios | Return vs lower partial moment of order n? | R | D | Kaplan & Knowles 2004 | missing |
| C42 | Up/down capture ratios | How much of up and down markets does it take? | R + benchmark | D | | missing |
| C43 | Cornish-Fisher / higher-moment adjusted Sharpe | Sharpe adjusted for skew and kurtosis? | R | D | Pezier & White 2008 | missing |
| C44 | Recovery factor | Net profit per unit of worst drawdown? | R | D | | partial |

