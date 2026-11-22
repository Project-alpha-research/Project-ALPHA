---
owner: data layer
sources:
  - packages/alpha-data/src/alpha_data/crypto/**
  - tests/unit/test_crypto_*.py
  - tests/bias_guards/test_crypto_*.py
verified: 15be891d490388ff
---

# Data layer invariants: crypto

Rules for the crypto part of `alpha_data`: storage, identity, features and offline Bybit context. The rest of the data layer is in [data.md](data.md).

## Crypto storage

[ADR-0032](../../adr/0032-governed-crypto-data-house.md).

- Bulk bytes live on the configured external volume; manifests and the control database stay internal. Before any write, `verify_ready` checks volume UUID,
  writability and the free-space reserve, failing closed. `verify_readable` checks mount and UUID only, without a write probe.
- Publish external bytes first and the internal manifest last. A manifest id is the SHA-256 of its canonical body; an existing path may be republished only
  with identical bytes. Revision lookup uses a per-store in-memory raw-manifest index, built once and updated on each write: discovery only, never evidence.
- Normalized bytes publish only after every input raw manifest re-verifies and the bytes match the quality report hash. Derived artifacts accept only
  normalized inputs.
- Bybit derivative trades and order-book snapshots require a `CryptoAcquisitionScopeV1` (research case, revision, reason); any other family refuses a
  scope. Unscoped historical captures stay readable but cannot enter governed snapshots.
- Storage paths are confined to their root; symlinks are refused.
- Cleanup deletes only `bulk/cache`. Staging, raw, normalized, snapshot, manifest and control roots are never removed.
- Retirement appends a hash-bound receipt under the admission lock and never deletes manifests, raw lineage or payloads. Only `inactive_quarantined` and
  `revoked_units_error` are valid reasons. Retired inputs are excluded from new admission and active inventories; full audits include them.
  `scripts/crypto_data_hygiene.py` audits references (`--report`) and repeats the audit under the lock before `--apply`; it fails closed on unreadable
  evidence and never retires referenced artifacts.
- Normalized reads are capped at 32 MiB and re-verify the artifact while reading.
- A governed snapshot member is its content (dataset, artifact key, artifact hash). Creation and every verification resolve it with one rule
  (`alpha_cli/_crypto_snapshot_members.py`): several retained captures of the same bytes count as one only if they agree on everything except per-fetch
  provenance (manifest ids, raw storage keys, receipt ids, fetch times); any other difference fails as ambiguous. Creation freezes members in canonical
  order, refuses a capture named twice, and members of one dataset must cover disjoint observed ranges.
  [ADR-0046](../../adr/0046-crypto-snapshot-members-are-content-addressed.md)
- Archive charts ([ADR-0038](../../adr/0038-local-confirmation-and-terminal-archive-charts.md)): inventory is discovery only; a chart read runs full
  manifest and raw-lineage verification, then checks dataset identity, units and the completed-bar cutoff. Reconstructed archive history does not establish
  point-in-time availability or research admission. A listed venue pair is no proof that bars are stored.
- A chart group joins archive segments only for one identical identity; overlapping bars must agree exactly or the read fails loud
  (`alpha_cli/_chart_data.py`).

## Crypto identity and features

- One primary authority per dataset family: Binance (CEX spot/futures), Bybit (derivatives/options),
  CoinGecko (identity/reference), GeckoTerminal (DEX pools), Coin Metrics Community (on-chain), Coinbase via
  CCXT (comparison only). No fallback changes venue, quote asset, units, frequency or evidence.
- Never merge USD, USDT and USDC. Keep each interval, venue, market type and quote currency a separate identity.
- Ticker-only joins are prohibited: `AssetMaster.resolve_ticker` always raises. Contract lookups need network
  plus contract address; native assets resolve only through a reviewed mapping.
- Reviewed native masters are label-frozen: `reviewed-native-v1` bytes never change; new assets go in a new
  label. An unknown label fails loud. Digests are pinned in `tests/fixtures/crypto/reviewed_native_asset_masters.json`
  and checked by `tests/unit/test_crypto_asset_master.py`. `reviewed-native-v1` (BTC, ETH) stays the default;
  `reviewed-native-v2` adds XRP and SOL and seeds `build_cross_provider_asset_master`.
- A feature's availability may never precede an input observation or its source availability, and no
  feature reads a later observation. Enforced by `tests/bias_guards/test_crypto_features_future_poison.py`.
- Per-provider fetch, parse, budget and availability rules (Binance, Bybit, CoinGecko, GeckoTerminal,
  DefiLlama) and coverage profiles are in [crypto providers](crypto-providers.md).

## Offline Bybit context
- Import qualified normalized Bybit linear artifacts into separate `context/bybit/linear/{funding,open_interest}/<SYMBOL>.parquet` tables.
  Verify manifest identity, Parquet size/SHA-256 and raw lineage (`input_manifest_ids`); provenance keeps source ids, fetch times and output hashes.
- Funding is known at settlement; intervals use the preceding 1/2/4/8-hour gap (first row: next gap; 2h after 1h is a missed settlement). Unknown stays null.
  Hourly open interest is known at interval start + one hour + five minutes. These historical clocks do not use late fetch times.
- Skip retired manifests. Collapse duplicates; latest linked raw fetch wins conflicts (no receipt: lowest), then manifest id. Over ten conflicts fails a symbol.
  Stage both families; caught publication errors restore previous files. Interrupted table/provenance pairs fail their hash check. Other symbols still import.
