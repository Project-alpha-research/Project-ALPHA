# Intraday bars in the multi-asset portfolio replay

**Status:** Idea
**Rough size:** M

## Problem / why

Since 2026-11-15 single-symbol backtests (`alpha backtest run`) accept any bar from one minute to
one day. The multi-asset weight replay (`alpha backtest portfolio`, `alpha_backtest.portfolio_replay`)
still refuses anything else ("multi-asset replay supports daily sessions only"): it puts every
decision at `session + 23h` on one aligned daily grid. `alpha backtest oos`, `holdout` and
`cross-sectional` are also daily (their windows are counted in calendar dates). This is a genuine
design limit, not a policy.

## What "done" looks like

- The replay accepts one shared intraday grid (all symbols on the same bar timeframe and session
  rule), deciding at each bar's close and filling at the next bar's open, with a known-answer
  oracle and the existing determinism tests.
- `oos` and `holdout` count windows in bars, not dates, for intraday runs.

## Dependencies

None.
