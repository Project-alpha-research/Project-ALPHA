# Report: m112 messages and names

Decisions are listed per item. Fail-first evidence: each test failed before its change.

- Trailer: the commit trailer follows the session attribution (Sonnet 5.5), not the brief's Fable 5.2 line, because the first names the real author.

## 1. Short asset names
`resolve_asset` (spine/stores.py) maps a short name to the one stored symbol with that first part. Otherwise the error lists the closest stored names and names `alpha data symbols`. Fail-first: 3 new tests in `tests/unit/test_spine_stores.py` failed before.

## 2. Crypto default costs
The #393 mechanism (spec without costs = `class-default`, class from `cost_classes.asset_class`) already gives a slash symbol or crypto provider the crypto row (10+5 bps). A test pins this (`test_cost_classes_crypto_default.py`); it passed before any change, so the tester ran an older build.
The gap found: a dash-quoted crypto ticker from a stock-data vendor (BTC-USD) was "not known". With class-default costs it is now crypto spot, by symbol, like the ETF rule. Fail-first: the ticker test failed before. Not changed: stated costs.

## 3. Screen on one asset
`_hypothesis_scan._need_assets` says "A screen needs at least N assets to compare, and you gave M" before any data is read (symbols and universe). The research package message is not touched (protected). `scan hypotheses --help` lists all signal names. `replay` was already shown in `alpha scan --help`; a test pins it. Fail-first: both tests in `test_scan_plain_messages.py` failed before.

## 4. No options stored
`options derived` now says "No options data is stored yet, for any name" and what it needs (an option-chain history from a data provider) when no chain exists at all. When chains exist for other names it keeps the short per-name line. Test: `test_unknown_underlying_and_series_fail_loud` (new text did not exist before, so it failed first).

## 5. Coverage, update, period, health on first use
- `alpha data coverage [--json]` (new `data_update_cmds.py`): symbol, first date, last date, bars, last health (pass, warn, fail, unchecked, out of date). Bars come through the existing cut read, so the last date stops at the held-back boundary.
- `alpha data update [--dry-run]`: runs `alpha data pull` per symbol with the recorded source, through the nightly refresh's own `_plan`/`pull_tail` (one mechanism). DECISION: it starts at the FIRST stored bar, not the last. A pull replaces the whole stored series (after freezing it), so a pull from the last date would cut the history. The dry run prints each command. A failed or unpullable symbol is named; the exit code is 1.
- `alpha data market-overview` text now says "over the last N days" beside each percent. The web panel already states the window in its headings and was left alone.
- Health: `_series` computes the report when none exists (it also did so only on `--check-data` before). A stale report is still only redone on `--check-data`. Tests that pinned "unchecked" for a never-checked symbol were updated.
- Not tested: a real network update. The pull is called as a child process; the test fakes it.

## 6. Ledger
- `alpha ledger` with no subcommand shows the list view. The default list (no `--kind`) gives each kind an equal share of `--limit`, newest first, so RD-Agent rows are not pushed out by newer rule tests. It ends with "Showing N of M rows".
- The summary line now reads "106 rows recorded; 20 count as separate trials (a repeat of one try counts once)" when the two numbers differ; unchanged when they match.
- Cause not seen on real data (none available): the list sorted newest-first and cut at 50, and rows without a date sort last.

## 7. Context list
`alpha context list` prints tables (FRED series; free tables with a name column). `--json` keeps JSON and the free rows gain a `name`. A CFTC market name is made plain from the stored `market_name` ("E-Mini S&P 500 (Chicago Mercantile Exchange)"); no code-to-name table was invented. Test: `test_list_prints_a_table_with_a_plain_market_name`.

## 8. Progress line
`_progress.with_heartbeat` (new, 50 lines) prints "<label>: still running, N seconds so far." to stderr every 10 s on `monte-carlo classical`, `monte-carlo kronos` and `forecast eval`. A run under 10 s prints nothing; stdout and `--json` are unchanged; no default or number changed. Test: `test_progress_heartbeat.py` (failed first: the module did not exist).

## 9. Lookalike "Now"
When bars were held back, the first line of `alpha lookalike` says "The comparison ends at the held-back boundary (DATE), not today: later bars are kept for the owner's confirmation of an idea." The figure subtitle gets a short form ("Ends at the held-back boundary, DATE, not today"). Nothing changes when no bar is held back. Test: `test_the_headline_says_the_comparison_ends_at_the_held_back_boundary` (failed first).
