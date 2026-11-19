---
owner: data layer
sources:
  - packages/alpha-data/src/alpha_data/options/**
  - tests/unit/test_options_schema.py
  - tests/unit/test_options_store.py
  - tests/unit/test_options_held_back.py
  - tests/unit/test_options_forward_guard.py
verified: ff7acf75edf4948e
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
a contract on another underlying, an expiry before the snapshot day, a `listed_on` after the snapshot day, a quote, trade or open-interest date
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
- The `known_at` filter uses the sidecars, so a future snapshot's Parquet file is never opened by an earlier read.
- A read cut-off must be timezone-aware. Names in paths (provider, underlying) allow only ASCII letters, digits, `_`, `.`, `-`,
  must start with a letter or digit and may not contain `..`; anything else is refused, so a path cannot leave the store folder.
- Read checks: the hash, the row count, the schema and the times in the sidecar must all match the Parquet file.
  A tampered Parquet or sidecar fails loud with the file name.
- Row labels (`ChainRow.labels`: `crossed`, `zero_width`, `iv_sentinel`) are computed from the stored row, so they come
  back with every read result.

## Research reads and forward use

The held-back period (`alpha_core.reserve.RESERVED_DAY`, no date literal here) works as in the bars store.
- Research reads cut. `snapshots_as_of` and `chain_as_of` take the caller's `as_of`, cap it at the last instant before the
  held-back day, and return only snapshots with `known_at` at or before that time. The result (`SnapshotsRead`, `ChainRead`)
  carries `held_back`: how many snapshots known by `as_of` the cap hid. A caller must disclose it. No quote, trade, greek or
  open-interest date from the held-back period is returned. A contract that expires after the boundary stays: it was listed
  and known before it. The expiry filter uses the capped day.
- Forward use reads the newest data on purpose. `forward_chain_as_of` returns the newest snapshot known at `as_of` with no cap.
  Use it only to follow an idea on paper, for the "active today" view or to show market data. Its name is deliberate.
- Guard: `tests/unit/test_options_forward_guard.py` fails if any source file other than the store names
  `forward_chain_as_of`. A forward-use home must be added to its list with a reason. Research-side code (spine, toolbox,
  Setup Lab, RD-Agent modules, the hypothesis scan) is therefore kept off it.
- Size: the fixture measures about 227 bytes per row for 54-row files and about 17 for a 1,920-row chain. The design estimate
  is about 35 bytes per row. Real chains compress less well than synthetic ones, so recheck with the provider's data.

## Synthetic fixture

`SyntheticAdapter(seed)` implements `OptionsAdapter` for the generic underlying `AAA`. Chains are deterministic for a seed.
The known surface IV is stored as the provided IV. Quotes use a placeholder price shape, not an option model.
Fixture prices are NOT arbitrage-free, and a solver cannot recover the stored IV from them. Never use the fixture to judge a
pricing or volatility method. The solver build must add a fixture priced with a stated model (for example Black-Scholes at the
surface IV) so a solver can recover the known volatility. No real market data or symbols are used.

## Not here yet

IV and greeks solver, derived series, health card rows, a provider adapter, the security-id map, delisted names,
`occ_symbol`, `deliverable`, `first_seen` and `last_seen` as separate fields, put-call parity reading, and a command group.
