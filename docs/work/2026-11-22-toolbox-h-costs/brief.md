# Brief: toolbox checks, family H. Cost and execution realism

Branch: `feat/toolbox-h-costs`. Module: `apps/alpha-cli/src/alpha_cli/toolbox/families/cost_realism.py`. Tests: `tests/unit/test_toolbox_cost_realism.py`.
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

## H. Cost and execution realism (22)

| # | Test | Question | Needs | Kind | Reference | ALPHA |
|---|---|---|---|---|---|---|
| H1 | Fee/slippage sweep * | How does return change as costs rise? | rule | D | | partial |
| H2 | Break-even cost * | How high can costs go before the edge is zero? | rule | D | | missing |
| H3 | OHLC spread estimators (Roll, Corwin-Schultz, Abdi-Ranaldo) | What spread can bars imply? | B | D | Roll 1984; Corwin & Schultz 2012; Abdi & Ranaldo...
| H4 | Square-root market-impact model | How much does our size move the price? | T + volume | D | Almgren & Chriss 2000 | missing |
| H5 | Capacity curve | Return versus capital deployed | RUN + volume | D | | missing |
| H6 | Liquidity-filter sensitivity (ADV, price floor) | Does the edge sit in untradeable names? | F + volume | D | | missing |
| H7 | Participation-rate / ADV cap | Does our order exceed a safe share of volume? | T + volume | G | | missing |
| H8 | Latency and next-bar fill check | Does acting on the next bar change results? | RUN | D | | partial |
| H9 | Fill-assumption test (limit vs market, touch vs trade-through) | Would limit orders really fill? | B | D | | missing |
| H10 | Overnight gap / stop-gap stress * | What if stops fill at the next open? | B | D | | missing |
| H11 | Stop-order slippage model | How much worse than the stop price? | B | D | | missing |
| H12 | Borrow-cost impact (shorts) | Does borrow fee erase the short leg? | T + X | D | | missing |
| H13 | Funding-rate cost (perps) | Does funding eat the edge? | T + X | D | | partial |
| H14 | Financing / margin interest | What does leverage cost? | T | D | | missing |
| H15 | After-tax return (short vs long term, wash sale) | What does the owner keep after tax? | T | D | | missing |
| H16 | Commission schedule and minimum ticket | Are small-order fees realistic? | T | D | | missing |
| H17 | Position-size granularity (whole shares, lot size) * | Does a small account's rounding change the trade? | T | D | | missing |
| H18 | Net-vs-gross turnover budget | How much alpha is left after churn? | F/T | D | | partial |
| H19 | Costs-charged audit | Were fees and slippage actually applied? | RUN | G | | have |
| H20 | Auction fill realism (open/close) | Could we trade at the auction price? | B | D | | missing |
| H21 | Volatility-scaled slippage | Does slippage rise with volatility? | B | D | | missing |
| H22 | Limit-order fill probability | How often does a resting order fill? | B | D | | missing |

