---
owner: data layer
sources:
  - packages/alpha-data/src/alpha_data/context/**
  - apps/alpha-cli/src/alpha_cli/context_cmds.py
  - apps/alpha-cli/src/alpha_cli/context_sources_cmds.py
  - apps/alpha-cli/src/alpha_cli/context_free_cmds.py
  - apps/alpha-cli/src/alpha_cli/context_derived_cmds.py
verified: bba514c75548b7f8
---

# Data layer invariants: context data

Rules and facts for context data in `alpha_data`: macro series, SEC filings, crypto derivatives, CFTC positioning, FINRA short volume
and published factor returns. They explain research results and never enter the bar store, snapshots or backtest inputs. The rest of the data layer is in
[data.md](data.md).

## Treasury, VIX and FRED macro series

Daily market series such as Treasury yields and the VIX have no revision history at FRED; each value is stored as
known from the day after its date and the series is marked `approximate`.

FRED/ALFRED macro series retain values as first published and every returned revision, with publication dates and
hashed provenance in `data_dir/context/fred/`: reference data for explaining research results, kept apart from the bar
store, snapshots and backtest inputs. `alpha context` pulls, lists and reads it. The default read takes publications
with `known_from <= cutoff` and no `known_until` or `known_until >= cutoff` (both ends inclusive). An observation with
no valid vintage is absent; a valid vintage with a missing value stays null and never falls back to an earlier value,
while an expired newest observation can leave an earlier still-valid one to carry. Explicit first-release and latest
views keep their historical and null-ended-only policies. Window endpoints carry the last observation knowable at each
boundary, capped by `--as-of`; window extrema use observation dates inside the window at that cutoff. The key comes
only from `FRED_API_KEY`; provider copyright restrictions are recorded in provenance. Live API behavior remains
unconfirmed. HTTP 400 on the full real-time range retries the same range in windows: one before 1920, five-year
buckets, and a final bucket ending 9999-12-31, for any cutoff year and without constructing year 10000. The schedule
follows the UTC date of the explicit aware-UTC `fetched_at` the CLI supplies, validated before transport or writes.
Identical vintage rows merge; conflicting or overlapping rows fail, comparing adjacent sorted rows of one series and
observation: an open-ended predecessor or a shared boundary is rejected, gaps remain valid. The generic launcher
classifies only `context list`, `show`, `window`, `show-edgar`, `show-binance` and `show-bybit` as safe local reads;
bare, unknown and `pull*` commands remain owner-only. The group appears under the Data menu.

## SEC EDGAR filings

SEC EDGAR filings and Form 4 insider transactions live under `context/edgar/`. A filing is known from its acceptance
time plus a 5-hour margin, because SEC's documentation does not say whether `acceptanceDateTime` is UTC or US Eastern:
the margin shows a filing late, never early (remove it once a live check confirms UTC). Rows with no readable
acceptance time are counted as rejected; an amendment keeps its own rows and clock. Earnings dates are the 8-K item
2.02 view. `ALPHA_SEC_USER_AGENT` (name and e-mail, as the SEC asks) is required and never stored or printed; requests
are 0.2 s apart and filing documents are cached. Live SEC check not yet run; Form 4 XML field names were checked
against SEC's ownership XML specification only.

## Binance and Bybit derivatives context

Binance USD-M funding (monthly files) and daily metrics (open interest, long/short ratios) live under
`context/binance/um/`, each ZIP checked against its `.CHECKSUM`. Funding is known at settlement, metrics five minutes
after their stamp. A changed stored value fails; missing periods are listed. File formats were checked live on
2026-11-16 (BTCUSDT). Reads show only rows known by an aware UTC cutoff; there is no "latest" view. Bybit linear
funding and hourly open interest are imported offline (`alpha context import-bybit --from <store>`) into
`context/bybit/linear/`, checksum-verified; funding is known at settlement, open interest 1 h 5 min after its hour
starts. First import 2026-11-17: 50 + 51 symbols, 2022-2026.

## CFTC positioning and FINRA short volume

Two free, key-less sources, added 2026-11-19 on the owner's "grab all the free data". They are inputs only: no signal
or statistic is defined on them. Only the derived series below read them; RD-Agent does not yet. Rows live in hashed tables under
`context/cftc/cot/<market>.parquet` and `context/finra/short_volume/<symbol>.parquet`, written by `store_events` and
read by `as_known_events` with an aware UTC cutoff, exactly as EDGAR and Binance rows are. Every row holds the period it
describes (`report_date`, `trade_date`) and `known_from`, the time it became public. Network use is confined to
`free_http.default_transport`: 30 s timeout, generic `Project-ALPHA/1.0` agent, one request per second, no redirects.
A day or market is fetched in full before anything is stored, and offline is a clear `DataError`.

- **CFTC Commitments of Traders** (legacy, futures only; Socrata dataset `6dca-aqww`, report as of Tuesday). The API
  has no publication field, but each row carries the system stamp `:created_at`, which matches live releases to the
  second since 2022-09 (checked 2026-11-19 against 2024-2026 rows). `known_from` is the later of the rule time (Friday
  15:30 US Eastern; in a week with a US federal holiday, the next non-holiday weekday after that Friday) and the stamp,
  and `known_basis` says which won. A stamp more than 120 days after the rule time is a bulk reload, so the rule time is used there. Reports as of
  before 2022-09-01 carry only the bulk stamp, so they use the rule time alone (`known_basis` `rule-only-era`). A
  missing or malformed stamp fails loud. One-off federal closures (2018-12-05, 2025-01-09) count as holidays.
  The stamp matters: the 2025 shutdown held reports of
  30 Sep to 10 Nov 2025 until 19 Nov to 12 Dec 2025, and the rule alone would show them 2 to 6 weeks early.
- **FINRA daily short sale volume** (consolidated file `CNMSshvol<date>.txt`). A trading day is known at 12:00 UTC on the
  next calendar day, later than FINRA's publication. The host answers 403 for a day with no file (weekend, holiday); such
  days are listed as missing, not stored. The file ends with a record count that must match its rows. Volumes are
  fractional. **Caveat, stored in every table's metadata and printed by every command:** the files cover trades reported
  to FINRA facilities only, not all exchange volume.
- **No revision overwrite.** A re-pull whose value differs from a stored period fails with `revised ...` and keeps the
  stored file. Identical rows merge. This is the Binance behaviour; neither source keeps vintages.
- **Invalid data fails loud** with the field named: non-numeric, non-finite or negative counts, short volume above total,
  duplicate or disordered dates, a changed header or column set, a date unlike its file's, a record count mismatch.
- **Reads.** `alpha context show-cftc-cot --market 13874A --as-of <UTC date or minute>` and `show-finra-short-volume
  --symbol SPY --as-of ...` return only rows with `known_from <= as-of`; `alpha context list` shows them under
  `free_context` with the caveat. Pull with `pull-cftc-cot` and `pull-finra-short-volume`. The only join of these rows
  to bars is `attach_context` (next section).

## Derived series and the one join

`alpha_data/context/derived.py` computes eight descriptive series (recipe `context-derived-v1`); `attach.py` is the one
module that puts them on bars. Windows are fixed in the recipe; a change is a new recipe version. No command, rule test,
setup or RD-Agent run uses them yet except `alpha context show-derived --series S --key K --asset SYMBOL`. It prints one
row per daily bar: value, `known_from`, age in days, stale. A coverage line counts the nulls by cause.

## Derived series: the eight

| Series | Formula on the native timeline, window includes the current row | Warm-up |
|---|---|---|
| `cot_nc_net_oi` | (noncomm long - short) / open interest | 1 report |
| `cot_nc_net_pct_156w` | percentile of `cot_nc_net_oi` over 156 reports: (average rank - 1) / (n - 1), from 0 to 1 | 156 |
| `cot_comm_nc_gap_pct_156w` | same percentile of (comm net - noncomm net) / open interest | 156 |
| `cot_nc_net_chg_4w` | `cot_nc_net_oi` minus its value 4 reports earlier | 5 |
| `sv_ratio` | short volume / total volume | 1 day |
| `sv_ratio_5d` | mean of `sv_ratio` over 5 rows | 5 |
| `sv_ratio_z_60d` | (`sv_ratio` - mean) / sample std (ddof 1) over 60 rows; null if all 60 are equal | 60 |
| `sv_breadth_z1` | share of stored names with `sv_ratio_z_60d` > 1 on that date, among names with a z that day | 60 |

Keys: a COT market code, a FINRA symbol, or `ALL` (breadth). `SELF` means the bar symbol. Breadth carries the label
"N stored names, not market-wide", with N the number of FINRA tables stored when it is read.

## Derived series: the as-of join rule

In order:
1. Read each table with `load_events` (hash-checked), keep rows with `known_from` <= the cutoff. Callers pass the spine reserve `CUTOFF`.
   A cutoff at or after the reserved instant is refused (`DataError`).
2. Drop rows whose period (`report_date`, `trade_date`) is on or after `RESERVED_DAY`. This is a filter. Bars stamped on or
   after that day are dropped too, so no output date reaches the reserved period.
3. Derive on the native timeline, sorted by period. `known_eff` = running maximum of `known_from` over all rows up to and
   including the row. It can be later than the window's own maximum: it is stricter, never looser. A value is never known
   before its newest input. Breadth takes the newest `known_eff` of the names on that date, then a running maximum.
   A COT `known_from` from the release rule alone (`known_basis` `rule` or `rule-only-era`) is moved one day later
   first (`derived.RULE_MARGIN`): stamped weeks show releases after the 16:00 US Eastern close, which the rule cannot
   see. Derived rows not known by the cutoff are dropped.
4. Decision instant `d` = `bar_known_at(ts)`. Backward as-of join on `known_eff` <= `d`, inclusive. The latest known value
   carries forward; that is not imputation, and `age_days` (date of `d` minus period) shows how old it is.
5. Stale: age above 17 days (COT) or 5 days (FINRA) gives null and `stale` true. Age equal to the limit is not stale.
   A null is never filled with zero. A bar before any known row is null with reason `not-yet-known`, not stale.
6. FINRA day t is known at 12:00 UTC on t+1: stock bar t+1 uses it, bar t does not. The BTC COT Friday release is before
   Saturday 00:00 UTC, so Friday's crypto bar (`ts` + 1 day) uses a stamped release; a rule-only one waits a day.
7. Delayed releases (shutdown gap). COT rows with `known_basis` `rule-only-era` whose report date is in a window of
   `derived.SHUTDOWN_WINDOWS` (2018-12-18 to 2019-03-05 and 2013-10-01 to 2013-10-29, inclusive) are unknown: null, reason
   `cot-delayed-release-unverified`. The catch-up dates were not verified, so the windows are wide on purpose.
   `cftc_cot.py` treats one-off closure days as holidays; this adds to that and does not change it. A percentile reads the
   other rows of its window and ranks the available values (window positions still count, so warm-up does not change).
   The 4-report change is null when either end is unknown.
8. Invalid input fails loud (`DataError`): zero or non-finite open interest or volume. A standard deviation of 0 gives null.
   Percentile ties use the average rank.

The result holds `ctx_<alias>`, `_age_days`, `_stale`, `_known_from`, `_reason`, plus `used_rows_sha256` per alias,
`source_table_sha256` per table and the recipe version. OSAP is not an input: at the cutoff it has no known rows, and
`context.published_factors` keeps reading it as hindsight.

## Derived series: result and guards

Guards: `tests/unit/test_context_attach_guard.py` lets only `attach.py`, the two stores and the listed display reader
`context_free_cmds.py` reach the COT or FINRA tables (`table_path`, `SOURCE` or `SCHEMA` under any alias, `getattr` on
the store, or the table path or source name as text), and lets only `align.py` and `attach.py` use `join_asof` or
`merge_asof`. A name built at run time escapes an AST scan; the future-poison guard checks behaviour.
`test_context_attach_poison.py` sets every row known after bar k to a huge value and checks bars up to k do not change;
a deliberately leaky join in the test does change. Outputs are readings, never verdicts or advice.

## Published factor returns (Open Source Asset Pricing)

Added 2026-11-19. Reference series for the question "is my strategy just a known published factor?". Inputs only: no
statistic is defined on them and no research command reads them. Source: Chen and Zimmermann, "Open Source
Cross-Sectional Asset Pricing" (openassetpricing.com); data on Hugging Face `OpenSourceAP/CrossSection`, one branch per
release (`Data-Release-2026.10`; older ones are `2025.10`, `2024.10` and so on). The dataset card states CC BY 4.0;
the code repository is GPL-2.0. Attribution is in `research/library/imported/osap/README.md`.

- **Files used.** `SignalDoc.csv` (the signal table) and `Portfolios/Full Sets OP/PredictorLSretWide.parquet`: column
  `date`, then one `Float64` column per predictor acronym (212 in release 2026.10), 1,200 rows. The long-short portfolio
  follows the original paper. Release 2026.10 holds 175,529 returns, 1926-01 to 2025-12; a null means no return.
- **Unit.** Percent in the file (5.0 = 5%). Mapped to decimals by dividing by 100 once (`percent_to_decimal`).
- **Month.** The source stamps each month with its last trading day. Stored `month` is the calendar month end.
- **Layer 1, `known_from`.** The later of 12:00 UTC on the day after the month ends and 00:00 UTC on the day after the
  release date of the vintage that holds the value. The files carry no release date, so `pull-osap-portfolios` requires
  `--released`, which a person types: it may not be earlier than the newest month in the file plus
  one day, and the stored `.json` records "release date supplied by the operator". Find the true date on the release
  page at openassetpricing.com or in the Hugging Face commit history of the release branch.
  `known_basis` is `release` or `month-lag`. Every row of a vintage uses that vintage's date: a revised value
  was not known before its release, so a read as of an earlier time sees nothing from it.
- **Layer 2, `published_year`.** The signal's publication year from the signal table, stored on each row, so a reader can
  split before and after publication. Year only: the source gives no sample-end rule finer than that.
- **Vintages.** Each release is its own file, `context/osap/portfolios/<release>.parquet`, with a hashed `.json`
  (release, release date, file URLs, licence, unit, rule). A new release is stored beside the old one; nothing is
  overwritten. A re-pull of a stored release that differs is refused (`new release`); an identical one is a no-op.
  `show-osap-portfolios --as-of T` uses the newest vintage with any row known at T, names it, or pins one with `--release`.
- **Fails loud.** Non-finite returns, duplicate or disordered months, a date that is not a month end, a column that is
  not a predictor in the signal table, a changed signal-table header, a release id that is not `YYYY.MM`, a future
  release date. Release 2026.10 uses CRSP v2 and revises 26 of 212 predictors against 2025.10 (its release notes).
- **Network.** `free_http` only: generic agent, 30 s timeout, one request per second. Its data files answer with a
  redirect to a signed host, so `Client.get_following` follows at most three redirects, https only, default port, no credentials in
  the address, to `huggingface.co` or `*.hf.co` (exact host match on the parsed name; the start address is checked too);
  any other host is refused. The caller passes the list, so no other source follows redirects. Only the generic agent
  header is sent.
- **Reserved period.** No research command reads these series. A future read must use `read_known` (same
  `as_known_events` cut-off) and stop at the reserved day from `alpha_core.reserve`, with no date typed in the reader; it
  must not add a second path. The series run to 2025-12, past the reserved day, so the stop is required.
