---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/data_cmds.py
---
# Stored data: symbols, coverage, pull

**Reach for it when** you need to know which symbols are stored, how much history each has, or must add a symbol.

**Commands**
```text
alpha data symbols --json                       # every symbol with stored bars
alpha data symbols --with-actions --json        # plus stored splits and dividends per symbol
alpha data candles SPY --start 2020-01-01 --end 2024-01-01 --json   # the bars themselves
alpha data source-status SPY --json             # where the series came from, pending receipts
alpha data health SPY                           # faults in the bars
alpha data pull SPY --start 2010-01-01 --end 2024-01-01
```
Use `--timeframe` for a bar size other than `1D`. `pull` needs `--start` and `--end`. The default source is `yfinance`.
A pull freezes the stored series as a snapshot first. If that fails, the pull stops and nothing changes.

**How to read it**
- Coverage: read the first and last bar of `candles`. A test can use only the bars that exist.
- `--with-actions` shows corporate actions with an estimated knowledge time. Treat those as less certain.
- `candles --end` is a cutoff in time. A bar after it, or a split not yet known then, is never shown.
- Run `data health` after each pull and before a test. A fault stops a test unless you accept it.

**What it cannot tell you**
- Stored does not mean correct. Prices come from the source, raw until adjusted by stored actions.
- `symbols` shows no quality. Delisted names missing from the store bias results toward survivors.

**Next** Run [data health](data-health.md), then the [rule test](rule-test.md) or a [setup find](setup-find.md).
