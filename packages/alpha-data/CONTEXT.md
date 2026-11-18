---
owner: data layer
sources:
  - packages/alpha-data/src/**
  - packages/alpha-data/pyproject.toml
verified: 638f802b62b82c2c
---

# alpha-data workspace

## Purpose

Data ingestion and storage: vendor adapters with receipts, the raw Parquet store, the
point-in-time `as_of` reader, corporate-action clocks, universe membership, immutable hashed
snapshots, and the crypto data house storage. It imports only `alpha_core` (import-linter
contract "alpha_data depends only on core"); `alpha_backtest`, `alpha_study` and `alpha_cli`
import it. It must never let a read see data that was not knowable at the cutoff.

## Read first

| Read | Section | When |
|---|---|---|
| [data invariants](../../docs/reference/invariants/data.md) | Package boundary | always |
| [data invariants](../../docs/reference/invariants/data.md) | Point-in-time store | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Point-in-time reads | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Invalid data fails loud | always |
| [data invariants](../../docs/reference/invariants/data.md) | Corporate actions | changing corporate-action storage or readers |
| [data invariants](../../docs/reference/invariants/data.md) | Universe membership | changing universe membership or survivorship handling |
| [data invariants](../../docs/reference/invariants/data.md) | Vendor receipts and promotion | changing vendor receipts, ingest or promotion |
| [data invariants](../../docs/reference/invariants/data.md) | Snapshots | changing snapshots or their verification |
| [data invariants](../../docs/reference/invariants/data.md) | Adapters and authority | adding or changing an adapter or its authority |
| [data crypto invariants](../../docs/reference/invariants/data-crypto.md) | Crypto storage | changing crypto storage, archives or retirement |
| [data crypto invariants](../../docs/reference/invariants/data-crypto.md) | Crypto identity and features | changing crypto identity or features |
| [data crypto invariants](../../docs/reference/invariants/data-crypto.md) | Offline Bybit context | changing offline Bybit funding or open interest |
| [architecture](../../docs/ARCHITECTURE.md) | Runtime data-directory layout | changing where data is stored |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Corporate actions: two clocks | changing splits, dividends or symbol changes |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Immutable, hash-bound artefacts | changing snapshots or receipts |
| [crypto provider invariants](../../docs/reference/invariants/crypto-providers.md) | — | changing `crypto/providers/` or coverage profiles |
| [command line crypto data](../../docs/reference/invariants/cli-crypto-data.md) | — | the change is driven by an `alpha crypto-data` command |
| [engineering rules](../../docs/reference/invariants/engineering.md) | Polars by default | touching an adapter or adding a dataframe library |
| [bar timeframes](../../docs/reference/invariants/data-bar-timeframes.md) | — | changing bar timeframes, intraday stores or intraday quality |
| [what this part is for](../../docs/reference/project/components/data-layer.md) | — | why it exists; before you keep, shelve or remove it |

## How to change it

- Code: `packages/alpha-data/src/alpha_data/`; bar timeframes (one minute to one day, the no-HFT boundary,
  one store per timeframe) in `timeframe.py`; exchange sessions, resampling and as-known alignment in
  `sessions.py`, `resample.py` and `align.py`; vendor adapters in `adapters/`, the crypto data
  house in `crypto/` and `crypto/providers/` (command-local raw-resource discovery is owned by
  `CryptoBulkStore` in `storage.py`); FRED macro vintages, SEC filings/insider events and
  Binance derivatives and offline Bybit context in `context/` (separate hashed tables under `data_dir/context/`,
  never bars or backtest inputs; event reads require an aware UTC cutoff).
- Daily OHLCV health checks and their supplied report cutoff live in `health.py`. See [the tool card](../../research/tools/data-health.md).
- Tests: `tests/unit/test_data_health_report.py`, `tests/unit/test_pit_*.py`, `test_parquet_store.py`, `test_snapshot.py`, `test_ingest*.py`,
  `test_corporate_actions.py`, `test_dividends_pit.py`, `test_universe_store.py`, `test_tiingo_*`, `test_alpaca_adapter.py`,
  `test_bar_timeframe.py`, `test_ingest_pipeline_intraday.py`, `test_sessions.py`, `test_resample.py`, `test_align.py`,
  `test_crypto_*`, `test_context_*.py` (all in `tests/unit/`); bias guards `tests/bias_guards/test_pit_*.py`,
  `test_survivorship.py`, `test_candles_pit.py`, `test_intraday_future_poison.py`, `test_crypto_*_future_poison.py`; integration
  `tests/integration/test_data_cli.py` and `tests/integration/test_crypto_*`.
- A new or changed read path needs its future-poison guard with a must-fail leaky twin
  (pattern: `tests/bias_guards/test_future_poison_pattern.py`).
- Check: `uv run python scripts/gate.py check` (lint, `lint-imports`, mypy, mapped tests and every
  bias guard). Pass aware UTC cutoffs in tests; `tests/unit/test_pit_tz.py` covers naive and DST cases.

## Outputs

- Tests: the bias guard for any read change; unit tests for new failure modes (typed `DataError`).
- The owning document: `docs/reference/invariants/data.md` (crypto providers:
  `docs/reference/invariants/crypto-providers.md`; crypto commands: `docs/reference/invariants/cli-crypto-data.md`).
