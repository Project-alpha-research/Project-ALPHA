---
owner: data layer
sources:
  - packages/alpha-data/src/alpha_data/pull_store.py
  - packages/alpha-data/src/alpha_data/snapshot_reuse.py
  - packages/alpha-data/src/alpha_data/series_diff.py
  - tests/unit/test_data_pull_freeze.py
  - tests/integration/test_data_pull_freeze_cli.py
verified: de5ae16dc460b70e
---

# Freeze before replace

A pull replaces a stored series. It never does so without a frozen copy. `pull_store.pull_into_store` is the one
home of this rule. Every download goes through it: `alpha data pull`, the nightly step N0 (a child `alpha data pull`),
the MCP tool `data_pull` (the same command) and the daily Tiingo cycle.

- Order: validate the new data (no write), freeze the stored series, replace. A failure before the replace leaves the
  stored series untouched. A failure inside the replace puts the old bytes back. Invalid data (a missing or
  non-finite value, a duplicate or naive timestamp, a quarantined receipt) writes no file and no snapshot.
- The first pull of a symbol has nothing to freeze and takes no snapshot.
- If the freeze fails, the pull stops before any write (`alpha data pull` exits 3) and names the reason. There is no flag
  to skip the freeze. A series is frozen only under the adapter and parser version that wrote it. If the version
  differs, the pull keeps refusing: nothing in ALPHA re-adopts a series under a newer adapter. A pull from another
  source freezes the series under the stored source and versions.
- Re-use: each new manifest entry holds `content_sha256`, the hash of the bars, actions and provenance digests. If it
  equals the hash in the symbol's most recent snapshot, no new snapshot is written and that id is returned ("reused").
  Old manifests have no such field. They are never matched, rewritten or deleted. `verify` checks old and new alike.
  A receipt-backed pull stores a new receipt each time, so its provenance and hash change on every pull.
- A pull reports counts and dates, never prices: bars added (count, first and last date), removed (count) and revised
  (count, first date, columns); the same counts for corporate actions. A revision also gives the notice "the provider
  revised N earlier bars; the earlier series is kept in snapshot <id>". The same data is in `--json`.
- An identical re-pull leaves the stored files byte-identical, so the series fingerprint in run identity is unchanged.
- Cost: a 30-year daily series is about 289 KB per snapshot. `alpha data snapshots` prints the total. Snapshots are
  never deleted automatically. Pruning is an owner decision and is not built.
- Not covered: the private acquisition stores of the comparison worker (a fresh store per batch) and the derived
  `RULES` projection bars. Neither holds a downloaded series that a pull replaces.
- Code: `pull_store.py`, `snapshot_reuse.py` and `series_diff.py` in `packages/alpha-data/src/alpha_data/`.
- Tests: `tests/unit/test_data_pull_freeze.py`, `tests/integration/test_data_pull_freeze_cli.py`.
