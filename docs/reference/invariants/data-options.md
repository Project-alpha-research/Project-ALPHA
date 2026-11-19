---
owner: data layer
sources:
  - packages/alpha-data/src/alpha_data/options/**
  - tests/unit/test_options_schema.py
  - tests/unit/test_options_store.py
verified: 856ba84773009f38
---

# Data layer invariants: options

Rules for `alpha_data.options`: the provider-neutral option chain records, their store and the synthetic fixture adapter.
No provider code, no network and no pricing model live here yet. The rest of the data layer is in [data.md](data.md).
The component page is [options data](../project/components/options-data.md).

## Records

All records are frozen dataclasses that check themselves on construction. A bad value raises `OptionsDataError`
(a `DataError`) and its `field` attribute names the field.

- `ContractId`: underlying id, root, expiry, strike (exact `Decimal`), right `C` or `P`, style `A` or `E`, multiplier,
  `listed_on` (or `None` when unknown) and `provider_symbol`. The identity `key` ignores `provider_symbol`, which is provenance only.
- `Quote` (bid, ask, sizes, `quote_ts`) and `Trade` (last, `last_ts`, volume) are separate records. A quote is never
  filled from a trade.
- `Greeks` carries `source` (`provided` or `computed`) and `model`. A chain row has two slots, `provided` and `computed`;
  a block in the wrong slot is refused. They are never mixed in one column.
- `ChainSnapshot`: contracts with quotes at ONE `snapshot_ts`, known from `known_at`.

## Invalid data fails loud

Errors (typed, naming the field): non-finite or negative prices, strike at or below zero, unknown right or style,
non-positive multiplier, naive or non-UTC datetimes, `known_at` before `snapshot_ts`, a duplicate contract in one snapshot,
a contract on another underlying, an expiry before the snapshot day, a `listed_on` after the snapshot day, a quote or trade
stamped after `known_at`, a snapshot written older than the newest stored one, a non-finite or negative provider IV.

Labels, not errors (`quote_labels`, `Greeks.labels`): `crossed` (bid above ask), `zero_width` (bid equals ask) and
`iv_sentinel` (a provider IV of exactly zero). Vendors publish such rows; the label lets a reader decide.
The 2026-11-19 design is silent on this; the choice is an open reading.

## Point-in-time store

- Layout: `<data_dir>/options/<provider>/<underlying_id>/<yyyy>/<yyyymmddThhmmssZ>.parquet` plus a `.json` sidecar with
  `sha256`, `rows`, `snapshot_ts`, `known_at`, `fetched_at`, `adapter_version` and `schema_version`.
  The design names `<date>.parquet`; a timestamp name allows more than one snapshot a day. Open reading.
- One flat Parquet row per contract; the snapshot fields repeat on each row. Strikes are stored as exact decimal text.
- Snapshots are append-only. The same content again is a no-op. Different content for an existing snapshot is refused.
  A read checks the hash, the row count and the schema, and rebuilds every record, so a damaged file fails loud.
- `snapshots_as_of(provider, underlying, when)` returns snapshots with `known_at <= when`. `chain_as_of` returns the newest one,
  without contracts not yet listed or already expired on the cut-off day. It returns `None` before the first snapshot.
- The `known_at` filter uses the sidecars, so a future snapshot's Parquet file is never opened by an earlier read.
- A read cut-off must be timezone-aware. A read at or after the held-back day (`alpha_core.reserve.RESERVED_DAY`) is refused.
  No date literal is repeated in this package.
- Size: the fixture measures about 227 bytes per row for 54-row files and about 17 for a 1,920-row chain. The design estimate
  is about 35 bytes per row. Real chains compress less well than synthetic ones, so recheck with the provider's data.

## Synthetic fixture

`SyntheticAdapter(seed)` implements `OptionsAdapter` for the generic underlying `AAA`. Chains are deterministic for a seed.
The known surface IV is stored as the provided IV. Quotes use a placeholder price shape, not Black-Scholes. The solver build
replaces it. No real market data or symbols are used.

## Not here yet

IV and greeks solver, derived series, health card rows, a provider adapter, the security-id map, delisted names,
`occ_symbol`, `deliverable`, `first_seen` and `last_seen` as separate fields, put-call parity reading, and a command group.
