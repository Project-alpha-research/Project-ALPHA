---
owner: data layer
sources:
  - packages/alpha-data/src/alpha_data/context/**
  - apps/alpha-cli/src/alpha_cli/context_cmds.py
  - apps/alpha-cli/src/alpha_cli/context_sources_cmds.py
  - apps/alpha-cli/src/alpha_cli/context_free_cmds.py
verified: da925d4f9e1b1ff3
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
or statistic is defined on them and RD-Agent does not read them yet. Rows live in hashed tables under
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
  `free_context` with the caveat. Pull with `pull-cftc-cot` and `pull-finra-short-volume`. No research command reads
  these yet. A research read must use the same `as_known_events` cutoff and reject periods from `RESERVED_DAY`
  (2024-01-01) on, as `daily_funding.py` does; it must not add a second path.

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
