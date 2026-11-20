---
owner: command line trial ledger read model
sources:
  - apps/alpha-cli/src/alpha_cli/spine/trial_record.py
  - apps/alpha-cli/src/alpha_cli/spine/trial_reader.py
  - apps/alpha-cli/src/alpha_cli/spine/trial_query.py
  - apps/alpha-cli/src/alpha_cli/ledger_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/deflation.py
  - apps/alpha-cli/src/alpha_cli/spine/ledger.py
  - tests/smoke/test_family_deflation_smoke.py
  - tests/unit/test_spine_deflation.py
  - tests/smoke/test_ledger_smoke.py
verified: c9f7b42d7a12c19e
---

# One trial ledger invariants

`alpha ledger` reads the spine ledger and the external RD-Agent factor/rule ledger as one
model. [ADR-0053](../../adr/0053-one-trial-ledger-read-model.md) owns the outcome mappings and
counting decision. Options are in the [command reference](../commands.md#alpha-ledger).

The run-folder commands `proposal` and `reply` exchange build choices with a waiting worker.
Between proposals, the command reads the worker's phase and its latest decision.
A reply publishes a file in that round's folder. Trial counts and owner approvals come from
their existing records. See the [discussion protocol](../../../workers/rdagent/propose-and-discuss.md).

## Sources and snapshots

- The spine source is `<home>/ledger/trials.jsonl`. `--rdagent-ledger PATH` overrides
  `[rdagent] factor_ledger = "/absolute/path"` in `<home>/ledger/sources.toml`.
  With neither, the `alpha ledger` commands read the RD-Agent ledger at its default location beside
  the data directory, `<home>/../runs/rdagent-trial-ledger/rdagent-factor-trials.jsonl` (the
  factor loop's `--trial-ledger`). Absent optional sources stay quiet in human output. Invalid TOML or configuration produces
  `LEDGER_SOURCE_INVALID`; configured files that do not exist are reported as missing.
- Read each file's bytes once. Acquire a shared `flock` only when its `.lock` exists, opened
  `rb`; never create directories, files or lock files. No writer or historical row is changed.
- Each mapped record carries an absolute source path and one-based line. Raw rows are retained
  in the snapshot for `show`; they are not reread from a possibly newer file.
- Non-object JSON, missing required mapping fields, unknown schemas/statuses and malformed
  field values become unknown rows with a reason. An incomplete final line is reported as
  `incomplete last line (a writer may be mid-append)`. File access failures fail loud.
- Every ledger snapshot command reports sources and unknown rows in JSON. Human output names each source read, includes unknown counts
  and reasons and ends with `Read-only view; the ledgers themselves are unchanged.`

## Families and queries

- `setup_study` and `setup_trade` count once; rows labelled `repeat` do not count. `setup_find` stays uncounted.
  Studies use `setup:<idea>` with Unicode case folding and collapsed whitespace; rule families stay unchanged.
  Studies have no comparable Sharpe. The stored `outcome` stays `inconclusive` below 30 complete primary outcomes,
  `supported (exploratory, not confirmed)` for a positive excess with random-date p ≤ 0.05 and agreeing halves,
  otherwise `not supported`; machines read it. A new row adds `evidence` (`too little to read`, `some evidence`, `not clear of chance`)
  and the reader prints that word; an old row reads through its old word. Studies use `setup-studies/<study_id>/manifest.json`;
  trades use `setup-trades/<trade_id>/manifest.json`. Trade readings count completed trades and apply the same conditions,
  with unavailable controls never giving `some evidence`. No count reads any of these words
  ([readings](cli-rule-readings.md#ledger-words)).
  `alpha validate` recognises existing spine families by registered rule strategy; other runs state
  `no ledger family: counted as one trial`. Re-running an existing run id reuses the family inputs
  in its manifest, never today's grown ledger. No ledger history or immutable run is rewritten.
- `alpha results show` adds the recorded count and live `family_counts` rows, outcomes and reader
  trials from the spine-only snapshot. Older runs have a null recorded count and an explicit reason.
## Queries and factor rows

- DuckDB is imported only for a query, connects to `:memory:` with external access disabled,
  and receives a Polars frame converted to Arrow. There is no database file or SQL file read.
- Questions are `by-family`, `by-outcome`, `by-asset`, `by-month`, `asset-history`,
  `family-trials`, `top-measure` and `repeats`. Bind values with `?`; reject unknown questions
  with `UNKNOWN_QUESTION` and missing/unlisted parameters with `BAD_PARAMETER`.
- `DEFLATION_FAIL` maps to rejected with recorded deflated Sharpe, threshold and trial count. A failed-deflation old
  CANDIDATE is labelled as derived; stored rows and trial counting stay unchanged. Every factor status has a plain reason.
- New factor rows count one declared primary-clock look; old V3 rows retain their per-clock counts.
  `family-looks-x2-floor-1` uses twice those looks, with a 1/(T-1) variance floor; q is a BH diagnostic.
  The reader exposes cutoff, m, confirmed, deflation inputs and expected chance passes; old DSR is labelled old rule.
- Factor figures name one clock: prefer the lead's per-clock block, otherwise explicitly label the daily mirror.
  New rows mirror all figures from `lead_clock` and record `figures_clock`; old daily mirrors remain readable.
- `SPREAD_FAIL` maps to rejected, retains its raw status and says "stopped by the spread check".
  Failed factors show their recorded failure reason and first error line. `LOOKAHEAD` and `UNSTABLE` map to invalid,
  with first-mismatch details in `list`; invalid rows retain their trial counts.
- New factor rows carry `universe_includes_delisted`: true gives `includes-delisted`, false gives `survivor-universe`.
  Without the field, a positive recorded "later delisted" count gives `includes-delisted`, survivors-only text gives
  `survivor-universe`, and other text gives `universe-not-recorded`. Strings and older text lists are read without rewriting rows.
  Missing bars alone never establish a delisting.
- Factor dates use UTC `recorded_at` when present; old rows keep the run-id date-prefix fallback.
- `by-asset` and `asset-history` normalise names for grouping only (`BTCUSDT` = `BTC/USDT`);
  names with `:` (perpetuals) stay separate; `list` and `show` keep the original name.
- Limits are 1–200, default 50. Top measures exclude nulls; p and q sort ascending and the
  other allowed measures descending. Undated rows group under `unknown` for by-month.

## Evidence checks

- Spine evidence resolves under the home directory. Factor evidence resolves under the
  RD-Agent file's grandparent, matching either folder name or `run-identity.json` to the recorded run id. Rule evidence requires a unique
  match one study directory below that root. Paths escaping the root and ambiguous matches fail; another run's
  unreadable `run-identity.json` only fails to match.
- `show` reports presence, current SHA-256 and match to the recorded digest; match is null
  when no digest was recorded. Missing evidence with a recorded digest does not match.
- These checks describe recorded evidence only; no test or research conclusion is recomputed.
