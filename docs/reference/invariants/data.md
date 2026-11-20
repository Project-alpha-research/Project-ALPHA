---
owner: data layer
sources:
  - packages/alpha-data/src/**
  - tests/unit/test_pit*.py
  - tests/unit/test_parquet_store.py
  - tests/unit/test_snapshot.py
  - tests/unit/test_ingest_pipeline.py
  - tests/unit/test_crypto_*.py
  - tests/bias_guards/test_pit_*.py
  - tests/bias_guards/test_source_future_poison.py
  - tests/bias_guards/test_universe_survivorship.py
verified: cda0440bb2af68e6
---

# Data layer invariants

Rules for `alpha_data`: raw storage, point-in-time readers, receipts, promotion, snapshots and crypto storage.
Project-wide rules live in [research integrity](research-integrity.md); this file holds the data-layer mechanics.

## Package boundary

- Import only `alpha_core` (plus numpy/polars); see [engineering § Import layers](engineering.md#import-layers).
- Never import `alpha_patterns` for a shared formula — copy the closed form and pin it equal by test.
  `crypto/features.py` re-implements `alpha_patterns.vsa.rolling_ols_residual`; parity is pinned in
  `tests/unit/test_crypto_defi_tvl_feature.py`.
- pandas appears only in `adapters/yfinance_adapter.py` — [engineering § Polars by default](engineering.md#polars-by-default).
- Commands live in `alpha_cli`. FRED, SEC, Binance and Bybit context stays apart from bars: [data layer](../project/components/data-layer.md).
- Daily Binance funding uses verified source bytes and UTC `known_from` days; [RD-Agent policy](../../../workers/rdagent/judge-rules.md#futures-funding).

## Point-in-time store

General rule: [research integrity § Point-in-time reads](research-integrity.md#point-in-time-reads).
[ADR-0005](../../adr/0005-point-in-time-firewall.md).

- Feed strategies, backtests and charts only through `PointInTimeSource.as_of` (typed `Bar`s) or
  `PointInTimeReader.as_of` (frame). Never hand `ParquetStore.read_bars` output to a decision. Full-history
  loads also go through the source with a far-future cutoff (`alpha_cli._runner.load_bars`).
- The firewall is `filter(ts <= when)` — inclusive. Keep `<=`. Enforced by
  `tests/bias_guards/test_pit_future_poison.py` (future poison plus a non-vacuity edit at `when`).
- `PointInTimeReader.as_of` raises `DataError` on a naive cutoff before reading any data, and converts a
  named-zone cutoff to UTC before comparing, so the inclusive instant survives DST. The host time zone never
  supplies an offset. Enforced by `tests/unit/test_pit_tz.py`.
- `dividends_as_of` also raises `DataError` on a naive cutoff, for the same reason: `astimezone(UTC)` would
  read the host zone.
- Typed reads validate bars only after cutoff filtering: an invalid future bar cannot break a past read; an
  invalid visible bar raises chained `DataError` with symbol, timestamp and reason. Never skip or coerce it.
  Enforced by `tests/bias_guards/test_source_future_poison.py`.
- A UTC cutoff says nothing about when a provider published or revised a value.
- The store holds raw, unadjusted bars and does not enforce `Bar` invariants (zero volume is legal).
  Validation happens at ingest and at the typed read.
- `write_bars` replaces a symbol wholesale and atomically (temp sibling, then `os.replace`). It rejects missing
  columns, a tz-naive `ts`, and duplicate timestamps, and sorts by `ts` — positional readers rely on one
  sorted, tz-aware row per bar.
- Store paths reject empty, `..`, backslash and absolute names. A slash symbol (`BTC/USD`) becomes a
  subdirectory, so it never collides with `BTC_USD`.
- A new or changed read path needs its future-poison guard with a must-fail leaky twin
  (pattern: `tests/bias_guards/test_future_poison_pattern.py`).

## Corporate actions

General rule: [research integrity § Corporate actions: two clocks](research-integrity.md#corporate-actions-two-clocks).
[ADR-0004](../../adr/0004-two-clock-corporate-actions.md).

- Knowledge gate: `known_actions` keeps actions whose `knowledge_time` is on or before the cutoff's UTC date.
  `knowledge_time` is `announce_date`, else `ex_date` (flagged `knowledge_is_estimated`).
- Application gate: prices rescale only for splits that are known and already ex (`ex_date` on or before the
  cutoff date). `split_factor` applies `1/ratio` to bars strictly before `ex_date`; volume divides by the same
  factor. An announced future split leaves every visible price untouched.
  Enforced by `tests/bias_guards/test_pit_corporate_action.py`.
- Dividends never touch prices. `dividends_as_of` returns knowledge-gated dividends (visible before ex) for
  the engine to credit at `pay_date`. Enforced by `tests/bias_guards/test_pit_dividend_event.py`.
- A split without `ratio` or a dividend without `amount` raises `DataError`.

## Universe membership

- A universe is a list of `alpha_core.UniverseMembership` intervals: `effective_from` inclusive,
  `effective_to` exclusive, optional `delisting_return`. It is stored wholesale as `universe/<name>.json`.
- The only sanctioned read is `alpha_core.members_as_of(memberships, when)`: it keeps names that later left
  and hides future additions. Never filter by current constituents. Enforced by
  `tests/bias_guards/test_universe_survivorship.py`, whose survivors-only leaky twin must fail.
- A symbol that later stopped trading stays readable as of dates it traded (`tests/bias_guards/test_survivorship.py`).
- `parse_universe_csv` fails loud on missing columns, an invalid row, or no rows.

## Vendor receipts and promotion

[ADR-0017](../../adr/0017-authoritative-daily-data-and-broker-paper-boundary.md). Path for every receipt-backed pull:
provider → immutable receipt → candidate → quality gate → canonical Parquet → snapshot.

- `stage_and_promote` refuses a `FetchResult` without identity, receipt and raw response, or whose symbol or
  row/action counts disagree with the receipt. The receipt's response hash and length must match the raw bytes.
- A candidate is quarantined, never promoted, on any of: duplicate timestamps; non-numeric, non-finite or
  non-positive prices; inconsistent OHLC; negative volume; a provider other than the configured authority;
  exchange-calendar gaps (stock/ETF); a stored session missing from the new pull; conflicting corporate actions
  (same type and ex-date); or a cross-source close difference above the threshold (default 1%, skipped on
  action dates). Enforced by `tests/unit/test_ingest_pipeline.py`.
- Corrections stay visible: the quality report lists changed timestamps with old and new row hashes.
- Only `promote_quarantined(..., approve_differences=True)` promotes a quarantined receipt — an explicit,
  owner-reviewed repair. It re-verifies the stored receipt bytes and candidate identity first.
- Promotion writes an immutable pre-promotion backup and a fail-closed marker before touching canonical
  files. An in-process failure restores the exact prior bytes. After a process interruption the marker stays
  and every read of that symbol raises until `rollback_interrupted_promotion(..., acknowledge=True)`.
- Immutable receipt, candidate and quarantine directories may be republished only with identical bytes.
- Provenance v2 embeds `DatasetIdentity` and `FetchReceipt`; three-field legacy provenance stays readable.
  `DatasetIdentity` accepts raw-price datasets at any bar timeframe: [bar timeframes](data-bar-timeframes.md).

## Freeze before replace

Every pull freezes the stored series first, reuses an identical snapshot and reports what it changed:
[freeze before replace](data-freeze-before-replace.md).

## Snapshots

General rule: [research integrity § Immutable, hash-bound artefacts](research-integrity.md#immutable-hash-bound-artefacts).

- `create_snapshot` refuses an existing id, builds in private staging, and publishes with one `os.rename`;
  concurrent writers publish exactly one complete snapshot. Never edit a published snapshot.
- Snapshot ids and manifest paths cannot escape the root: no `/`, `\`, `..` or leading `.` in ids; no
  absolute or parent paths and no symlinks in manifests.
- The copy is bound to the source inodes. If bars, actions or provenance change during the copy, or a
  promotion is pending, creation fails.
- Source relabelling is refused: stored provenance must equal the declared source, adapter and parser
  versions, and a `ccxt:` snapshot requires provenance.
- `verify_snapshot` re-hashes every file against the manifest. `snapshot_manifest_hash` verifies first and
  then hashes the manifest bytes — that digest is what run identity binds.
- Tests: `tests/unit/test_snapshot.py`; promotion/snapshot interplay in `tests/unit/test_ingest_pipeline.py`.

## Adapters and authority

- Tiingo EOD is the authority for stock/ETF daily history. yfinance, Stooq and the interim Alpaca source are
  comparison only and never replace qualified Tiingo history. Alpaca's rules (SIP only, raw bars plus actions,
  split cross-check, byte-exact pages): [ADR-0047](../../adr/0047-alpaca-interim-stock-source.md), `test_alpaca_adapter.py`.
- Adapters return raw prices plus explicit actions. Yahoo serves split-adjusted OHLCV, so
  `parse_yfinance_history` reconstructs raw prices and fails loud if a split's ex-date jump is missing.
- Tiingo parsing rejects naive or out-of-range dates, non-finite or non-positive prices, and adjusted/raw
  ratios that disagree within a row. Transport failures expose only the exception type, with context
  suppressed; the API key travels only in a header. A bounded read keeps its byte ceiling (1 byte to 32 MiB).
  Enforced by `tests/unit/test_tiingo_adapter.py` and `tests/unit/test_tiingo_bounded_fetch.py`.
- Stooq never solves, bypasses or works around its "verify your browser" check: it sends one request under a
  generic client name and fails loud on a challenge page, its per-IP "Access denied" and HTML bodies; HTTP
  errors and interrupted reads (`IncompleteRead`, timeouts, connection errors) become a typed `DataError`.
  No error message points to another source.
- CCXT accepts only `coinbase` and `binance`, returns completed intervals only, never sends `since=0` (Coinbase
  answers it with the latest bars), and keeps venue-qualified `ccxt:<exchange>` provenance byte-compatible.
  It paginates past per-call caps; `fetch(date, date)` delegates to `fetch_timeframe` (daily by default).
- `CCXTAdapter.first_bar` is a daily listing-date probe, never a history read: it checks `load_markets`,
  scans forward from 2009 in page-sized windows, and fails loud on an unknown market, no history, or a bar
  earlier than requested. It stores nothing.
- QuantPad is no longer a provider: its adapter and archive code were removed on 2026-11-14
  ([ADR-0018 note](../../adr/0018-quantpad-external-research-data-boundary.md#owner-supersession--2026-11-14)).
  Datasets registered earlier from a QuantPad receipt stay readable and research-only, and the web app
  still files old QuantPad runs under equities (`alpha_web._runs._EQUITY_SOURCES`).

## Crypto storage
Moved to [data-crypto.md § Crypto storage](data-crypto.md#crypto-storage).

## Crypto identity and features
Moved to [data-crypto.md § Crypto identity and features](data-crypto.md#crypto-identity-and-features).

## Offline Bybit context
Moved to [data-crypto.md § Offline Bybit context](data-crypto.md#offline-bybit-context).

## Code map

Data ingestion and storage: vendor adapters with receipts, the raw Parquet store, the
point-in-time `as_of` reader, corporate-action clocks, universe membership, immutable hashed
snapshots, and the crypto data house storage. It imports only `alpha_core` (import-linter
contract "alpha_data depends only on core"); `alpha_backtest`, `alpha_study` and `alpha_cli`
import it. It must never let a read see data that was not knowable at the cutoff.

- Code: `packages/alpha-data/src/alpha_data/`; bar timeframes (one minute to one day, the no-HFT boundary,
  one store per timeframe) in `timeframe.py`; exchange sessions, resampling and as-known alignment in
  `sessions.py`, `resample.py` and `align.py`; vendor adapters in `adapters/`, the crypto data
  house in `crypto/` and `crypto/providers/` (command-local raw-resource discovery is owned by
  `CryptoBulkStore` in `storage.py`); FRED macro vintages, SEC filings/insider events and
  Binance derivatives, offline Bybit, CFTC positioning and FINRA short-volume context in `context/` (separate hashed tables under `data_dir/context/`,
  never bars or backtest inputs; event reads require an aware UTC cutoff); provider-neutral
  option chains, their point-in-time store (research reads cut at the held-back day; forward use through a named
  reader), a synthetic fixture and a European (closed form) and American (binomial tree) implied-volatility and
  greeks solver in `options/` ([rules](data-options.md)).
- Daily OHLCV health checks and their supplied report cutoff live in `health.py`. See [the tool card](../../../research/tools/data-health.md).
- Tests: `tests/unit/test_data_health_report.py`, `tests/unit/test_pit_*.py`, `test_parquet_store.py`, `test_snapshot.py`, `test_ingest*.py`,
  `test_corporate_actions.py`, `test_dividends_pit.py`, `test_universe_store.py`, `test_tiingo_*`, `test_alpaca_adapter.py`,
  `test_bar_timeframe.py`, `test_ingest_pipeline_intraday.py`, `test_sessions.py`, `test_resample.py`, `test_align.py`,
  `test_crypto_*`, `test_context_*.py`, `test_options_*.py` (all in `tests/unit/`); bias guards `tests/bias_guards/test_pit_*.py`,
  `test_survivorship.py`, `test_candles_pit.py`, `test_intraday_future_poison.py`, `test_crypto_*_future_poison.py`; integration
  `tests/integration/test_data_cli.py` and `tests/integration/test_crypto_*`.
- Check: `uv run python scripts/gate.py check` (lint, `lint-imports`, mypy, mapped tests and every
  bias guard). Pass aware UTC cutoffs in tests; `tests/unit/test_pit_tz.py` covers naive and DST cases.
- Tests: the bias guard for any read change; unit tests for new failure modes (typed `DataError`).
