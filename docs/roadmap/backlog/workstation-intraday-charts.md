# Intraday candles and run charts in the Workstation

**Status:** Idea
**Rough size:** M

## Problem / why

Since 2026-11-15 intraday bars work from the command line, and the Workstation run list names an
intraday run's bar size (M5, H1). The browser screens still assume daily bars: the linked context
accepts only `1D`, the chart toolbar enables only D1 ("daily data only"), `/api/candles` passes no
timeframe to `alpha data candles`, the recorded equity and trade tables show dates without times,
and evidence markers snap to one candle per day. An intraday run is listed but its price chart and
trade times are not readable there.

## What "done" looks like

- The chart toolbar offers the bar sizes a store holds; `/api/candles` passes `--timeframe`,
  `--from-timeframe` and `--session`.
- Run charts and trade tables show times for intraday runs; nothing changes for daily runs.
- Browser tests for one intraday run and one daily run.

## Dependencies

A rebuilt web bundle (needs the network).
