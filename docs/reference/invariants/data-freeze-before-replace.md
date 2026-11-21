---
owner: data layer
sources:
  - packages/alpha-data/src/alpha_data/pull_store.py
  - packages/alpha-data/src/alpha_data/snapshot_reuse.py
  - packages/alpha-data/src/alpha_data/series_diff.py
  - tests/unit/test_data_pull_freeze.py
  - tests/integration/test_data_pull_freeze_cli.py
  - tests/unit/test_data_pull_freeze_attacks.py
  - packages/alpha-data/src/alpha_data/pipeline.py
verified: c62e25685530b285
---

# Freeze before replace

A pull replaces a stored series. It never does so without a frozen copy. `pull_store.pull_into_store` is the one
home of this rule. Every download goes through it: `alpha data pull`, the nightly step N0 (a child `alpha data pull`),
the MCP tool `data_pull` (the same command) and the daily Tiingo cycle.

- Order: validate the new data (no write), freeze the stored series, replace. A failure before the replace leaves the
  stored series untouched. Invalid data (a missing or non-finite value, a duplicate or naive timestamp, a quarantined
  receipt) writes no file and no snapshot.
- Replace: the old files are first copied to a promotion backup, and a promotion marker is written. While the marker
  exists every read of the symbol refuses, so a kill never leaves a silent mix of new bars and old actions or
  provenance. A failed write puts the old bytes back. If that fails too, the pull exits 4, the marker stays, and the
  message names the backup, the snapshot and `alpha data rollback-promotion SYMBOL --acknowledge`. A pull without a
  receipt deletes its backup after it ends cleanly. The snapshot is the lasting copy.
- One pull at a time: a pull holds an exclusive lock on its store folder; a second pull waits. Readers take no lock.
  Each file is replaced by an atomic rename, and reads refuse while the marker exists.
- The first pull of a symbol has nothing to freeze and takes no snapshot.
- If the freeze fails, the pull stops before any write (`alpha data pull` exits 3) and names the reason. There is no flag
  or variable to skip the freeze. The series is frozen under the source and versions in its stored provenance. A series
  from an older adapter is frozen under that older version, and the report says so (`older_versions`). A series with no
  provenance is frozen with source `unrecorded`.
- Re-use: the content hash of a symbol is the hash of the bars, actions and provenance digests that every manifest
  already holds. It is computed, never stored, so manifests keep the bytes they had before and the manifest hash in
  run and scan identity does not change. If the stored series hashes like the symbol's most recent snapshot and that
  snapshot's files verify, no new snapshot is written and that id is returned ("reused"). A tampered or forged
  snapshot is never reused. No manifest is rewritten or deleted. A receipt-backed pull stores a new receipt each time,
  so its provenance and hash change on every pull.
- A pull reports counts and dates, never prices: bars added (count, first and last date), removed (count) and revised
  (count, first date, columns); the same counts for corporate actions. A revision also gives the notice "the provider
  revised N earlier bars; the earlier series is kept in snapshot <id>". The same data is in `--json`.
- An identical re-pull leaves the stored files byte-identical, so the series fingerprint in run identity is unchanged.
- Cost: a 30-year daily series is about 289 KB per snapshot. `alpha data snapshots` prints the total. Snapshots are
  never deleted automatically. Pruning is an owner decision and is not built.
- Not covered: the private acquisition stores of the comparison worker (a fresh store per batch) and the derived
  `RULES` projection bars. Neither holds a downloaded series that a pull replaces.
- Code: `pull_store.py`, `snapshot_reuse.py` and `series_diff.py` in `packages/alpha-data/src/alpha_data/`.
- Tests: `tests/unit/test_data_pull_freeze.py`, `tests/unit/test_data_pull_freeze_attacks.py`,
  `tests/integration/test_data_pull_freeze_cli.py`.
