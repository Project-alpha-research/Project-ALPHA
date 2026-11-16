# One crypto store for backtests, with receipts

**Status:** Idea
**Rough size:** M

## Problem / why

Found on 2026-11-15 while making intraday bars work end to end. ALPHA keeps crypto prices in two
places. The governed crypto store (`alpha crypto-data`) keeps Binance's raw archive files, quality
reports and content-addressed snapshots, and already handled 1-hour and 5-minute bars. The stock
store, which `alpha backtest` reads, gets crypto only through `alpha data pull --source ccxt`,
which keeps no receipt and no raw provider pages (legacy provenance, quality "legacy_unqualified").
So the better-kept data was not usable for backtests, and the data backtests used is the weakest.
A thin bridge now exists (`alpha backtest run --manifest-id`, reading one verified archive dataset
group), but runs cannot bind a frozen crypto snapshot id, and the CCXT path is still unqualified.

## What "done" looks like

- `alpha backtest run` (and later `oos`, `portfolio`) can name a frozen crypto snapshot and an
  instrument, and the run identity binds the snapshot hash.
- The CCXT pull either keeps receipts and raw pages like Alpaca, or is retired for backtests in
  favour of the governed store.

## Dependencies

None.
