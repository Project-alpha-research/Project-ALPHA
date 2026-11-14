---
owner: data layer
sources:
  - packages/alpha-data/src/alpha_data/timeframe.py
  - packages/alpha-data/src/alpha_data/pipeline.py
  - packages/alpha-data/src/alpha_data/snapshot.py
  - packages/alpha-data/src/alpha_data/adapters/alpaca_adapter.py
  - packages/alpha-data/src/alpha_data/adapters/ccxt_adapter.py
  - packages/alpha-data/src/alpha_data/pit.py
  - packages/alpha-data/src/alpha_data/sessions.py
  - packages/alpha-data/src/alpha_data/resample.py
  - packages/alpha-data/src/alpha_data/align.py
verified: 8348f6be6c0b
---

# Bar timeframes

What must hold for bars of any timeframe in the stock/ETF/CCXT store. The rest of the data layer:
[data invariants](data.md).

## Rules

Owner decision 2026-11-15: there is no daily-only rule. Daily (`1D`) is the default, not a limit.

- `BarTimeframe` covers 1 to 59 minutes, 1 to 23 whole hours, and one day; canonical spellings are
  `1D`, `<n>m`, `<n>h`. Longer bars are a design limit (resample stored daily bars).
- The one refusal is the no-high-frequency-trading boundary: sub-minute bars and tick, trade, quote or
  order-book data raise `DataError` naming the owner's rule (`parse_timeframe`).
- A stored bar's `ts` is the START of its interval in UTC; an intraday bar is known only at `ts + duration`.
  Daily bars keep the session-date 00:00 UTC stamp. Every intraday bar start lies on one grid that restarts
  at each UTC midnight (`BarTimeframe.is_aligned`).
- Each timeframe has its own complete store root: `store` for daily, `store-<canonical>` (for example
  `store-5m`) otherwise (`store_dir`). Receipts, quality, promotion and provenance work per root, so
  intraday bars never mix with daily bars. A snapshot of a non-daily store records `"timeframe"` in its
  manifest; daily manifests have no such key (`snapshot_timeframe` reads it, default `1D`).
  `verify_snapshot` and `snapshot_manifest_hash` take the timeframe the caller will read, default `1D`, so
  every daily consumer refuses an intraday snapshot instead of reading its bars as days.
- Intraday stock pulls are bounded by exchange-local session dates (New York midnight to midnight), so the
  "stored session missing from the new pull" check compares in that timezone: a winter after-hours bar
  stamped after 00:00 UTC belongs to the earlier session.
- `parse_timeframe` refuses `1M`, weeks and years rather than guess (`1M` is a month in pandas and CCXT).
- Intraday stock/ETF quality: per exchange session (DST and half days from `exchange_calendars`), every
  timeframe-aligned bar whose interval meets regular hours must be present (`intraday_gap`), a session with
  none is a `calendar_gap`, and an off-grid bar is `misaligned_bar`; all critical. Pre-market and
  after-hours bars are kept and counted (`extended_hours_rows`). Tests: `tests/unit/test_bar_timeframe.py`,
  `tests/unit/test_ingest_pipeline_intraday.py`.

## Reading intraday bars

- The firewall: an intraday read at cutoff `when` returns only bars with `ts + duration <= when`
  (`PointInTimeReader(timeframe=...)`); the daily read is unchanged. Corporate-action knowledge and
  ex-date gates, and each bar's split factor, use the exchange-local date (`session_date_of`; UTC for
  crypto), so an after-hours bar stamped after 00:00 UTC belongs to its New York session.
- Sessions (`sessions.py`): `regular` (exchange hours; a bar counts only when `open <= ts` and
  `ts + duration <= close`, so a clock-aligned 09:00 hourly bar is dropped), `extended` (every bar the
  provider returned), `continuous` (24/7, no calendar). Stocks default to `regular`, crypto to `continuous`.
- Resampling (`resample_bars`): the target must be a whole multiple of the source. Stock bins start at
  each session's open and are cut at its close (half days included); a daily target gives one bar per
  session at the session date 00:00 UTC. Crypto bins sit on the UTC grid. Only regular-session input is
  resampled. Every stock session is checked from open to close and every exchange session between the
  first and last bar must be present. A bin that ends after `known_by` (default: the data's own end) is
  still forming and is dropped; any other incomplete bin or missing session fails loud. OHLCV: first open, max high, min low, last close, summed volume.
- Alignment (`align_as_known`): each finer bar gets the latest coarser bar whose known time is at or
  before the finer bar's known time (daily stock bars are known at the session close), joined on known
  times, never on bar starts. Known time is `bar_known_at`.
- `_runner.load_bars(..., timeframe=, source_timeframe=, session=)` and `alpha data candles --timeframe
  --from-timeframe --session` use these; a store or snapshot holding another bar size fails loud.
  Cutoffs accept a date (end of that UTC day, the historical meaning) or an ISO instant with an offset
  (`parse_cutoff`). A daily read at an instant inside a day keeps only bars already closed then
  (`bar_known_at`: the session close for stocks, the next UTC midnight for crypto).
- Known limits: corporate-action knowledge is date-level (an action known on day D is visible from 00:00
  local on D, so a dividend announced after the close shows in that morning's intraday read; splits are
  gated on the ex-date and are unaffected). A session's last resampled bin may be shorter than the target
  (it ends at the close) but carries the target's duration, so its known time errs late, never early.
- Guards: `tests/bias_guards/test_intraday_future_poison.py` (reader, resampler and alignment, each with
  a leaky twin that must differ); unit tests `test_sessions.py`, `test_resample.py`, `test_align.py`,
  `test_pit_intraday.py`.

## Adapters

- Alpaca intraday: the SIP feed, bars exactly as Alpaca returns them (pre-market and after-hours
  included), stamped at the bar start; requests run from New York midnight of the first session date to
  the second before New York midnight after the last; the split cross-check uses each bar's New York
  date. Alpaca hourly bars are clock-aligned (the 09:00 New York bar holds 09:00-09:59), so hours that
  start at the 09:30 open are resampled from minute bars. Tests: `tests/unit/test_alpaca_adapter.py`.
- CCXT intraday: an intraday series must be a contiguous grid; a missing bar fails loud (crypto trades
  24/7; Coinbase omits buckets with no trades, so sparse pairs at short bars are refused). CCXT pulls keep
  no receipt or raw pages (legacy provenance). Tests: `tests/unit/test_ccxt_intraday_timeframe.py`.
