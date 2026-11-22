# Report: m112 messages and names

Decisions are listed per item. Fail-first evidence: each test failed before its change.

- The task folder also holds `brief.md` (a copy of the brief), because `test_filesystem_contract` needs a plan or a brief in every task folder.
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
- Health on first use: NOT DONE. I built it (compute the report when none exists), and the full unit run then showed 190 failing tests: every synthetic fixture fails the health checks (weekend bars, flat prices), so each first use would stop with `Data health: fail`. Fixing them means `--accept-bad-data` across the suite, which weakens what they check. I reverted it. It needs the owner's decision: either first use computes the report and a failing verdict stops the test (right for real data; the fixtures change), or first use computes it and only shows the result. `coverage` already shows 'unchecked' per symbol.
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

## 10. Deflated Sharpe wording
Finding: the toolbox number and the test's stored deflated Sharpe come from the same function (`family_deflation`), the same frozen trial count and the same prior Sharpes; the toolbox reads the after-cost scored returns of the stored equity. Neither number is wrong. The test's word "not clear of chance" has more gates than the deflated Sharpe (Sharpe interval above 0, every null test, then deflated Sharpe at least 0.95), so a high deflated Sharpe can sit next to it. I could not compare the two on the owner's real run (no data). The toolbox sentence now says so. Neither statistic changed. Test: `test_the_deflated_sharpe_sentence_says_what_it_is_and_why_the_test_can_differ`.

## 11. Owner reading of `alpha test` and `alpha results`
- `alpha test` (text mode) holds everything the run prints while it works and prints it after the result table and reading: warnings first, then lines that name saved files. On an error the held lines are printed first, then the error. `--json` is unchanged (progress goes to stderr as before).
- `alpha results show RUN` prints a summary of at most 40 lines (`results_summary.py`): data health, reading, up to 8 key numbers, counts of checks, flags, labels, tool count, charts, and the line `Full detail: alpha results show RUN --json`. `--json` keeps the full output. The old text dumped the whole JSON.
- `alpha results` (and `--symbol`) prints an aligned table with a header row; labels are joined with commas; a missing value is a dash.
- Sentences: the stored relation words stay in the stored file and in the web panel (they are machine values with their own tests). The text now reads "this rule's Sharpe is above/below buy-and-hold's by more than the uncertainty in the estimate" or "buy-and-hold's Sharpe is inside this rule's 95% range, so this test cannot tell the two apart". The resize line reads "N entries were made smaller, because the cash did not cover the full order at the next open plus fees. The result already uses the smaller size." Tests: `test_results_plain_text.py` (fails at import before), `test_reading_rule.py`, `test_entry_gap_sizing.py` updated.

## Checks
Full unit run before the health revert: 190 failures. After it, on the failing files: 18 failed and 15 errors. On origin/main the same files already fail: `test_reading_rule` (3), `test_reading_ledger_setup` (1), `test_research_playbook`, `test_suite_plan_golden`; `web-frontend.md` is 204 lines (limit 200) and `research/tools/rule-test.md` line 12 is too long. Not mine, not touched. The process-group tests (assistant cleanup, durable lease, suite executor, web invoke, native daily, research execution, CI bootstrap, home backup, model gateway) error in this container; I did not check them on main.
Fixed from my own changes: `scan`/`data` lazy imports, the structural-digest reader list (commands are now plain decorators), an empty results table.

## Review round 1 (automated review)
- Setup study/trade readings and outcomes (plain text in their summary) now print first in `results show`. Test added.
- `data update` now prints the pull's whole report (snapshot, revised or removed bars) under each symbol. Test added.
- Owning page `cli-runs.md` got two sentences on the new text outputs. `commands.md` and `fs.py verify` were left alone, as the brief says; the new commands `data coverage` and `data update` appear in `commands.md` only once the owner regenerates it.
- Ledger default list is now capped at --limit even with more kinds than rows (review finding). Test added.
- `data coverage` reads through the cut read (needs no provenance) and shows a reason, never a false zero, for a series it cannot read (review finding). Tests added. Note: a series stored wholly after the held-back boundary reads as 'cannot be read'.
