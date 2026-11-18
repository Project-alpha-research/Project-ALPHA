---
owner: command line trial ledger read model
sources:
  - apps/alpha-cli/src/alpha_cli/spine/trial_record.py
  - apps/alpha-cli/src/alpha_cli/spine/trial_reader.py
  - apps/alpha-cli/src/alpha_cli/spine/trial_query.py
  - apps/alpha-cli/src/alpha_cli/ledger_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/deflation.py
  - tests/smoke/test_family_deflation_smoke.py
  - tests/unit/test_spine_deflation.py
  - tests/smoke/test_ledger_smoke.py
verified: f2cbec34f9c54b20
---

# One trial ledger invariants

`alpha ledger` reads the spine ledger and the external RD-Agent factor/rule ledger as one
model. [ADR-0053](../../adr/0053-one-trial-ledger-read-model.md) owns the outcome mappings and
counting decision. Options are in the [command reference](../commands.md#alpha-ledger).

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
- Every command reports sources and unknown rows in JSON. Human output names each source read, includes unknown counts
  and reasons and ends with `Read-only view; the ledgers themselves are unchanged.`

## Families and queries

- `setup_study` and `setup_trade` count once; rows labelled `repeat` do not count. `setup_find` stays uncounted.
  Studies use `setup:<idea>` with Unicode case folding and collapsed whitespace; rule families stay unchanged.
  Studies have no comparable Sharpe. Outcomes are `inconclusive` below 30 complete primary outcomes,
  `supported (exploratory, not confirmed)` for a positive excess with random-date p ≤ 0.05 and agreeing halves,
  otherwise `not supported`. Studies use `setup-studies/<study_id>/manifest.json`; trades use `setup-trades/<trade_id>/manifest.json`.
  Trade readings count completed trades and apply the same support conditions, with unavailable controls never supporting.
- Families remain separate: spine rule, tool, setup and other families, `rdagent-factors`,
  and `rule:<family_id>`. Keep recorded family size separate from the reader count.
- `family_counts` reuses the existing RD-Agent `trial_family` function. Unknown RD-Agent rows
  contribute conservatively even if there are no mapped factors; an unmapped row of a factor
  schema goes through `trial_family` itself, other unknown rows add one each. `all_trials` is the sum of family
  counts plus unknown spine rows: each row once, never doubled (ADR-0053).
- Rule-test deflation reads only the spine ledger, never `sources.toml` or RD-Agent. Reader version 1
  counts prior `spine:<rule>` trials excluding repeats and errors, plus this run, scored sensitivity
  variants and all unknown spine rows. It is raised to the wider count of same-asset tests of any
  rule, this run and its variants when that is larger.
  Trials of the same test (spec hash, symbol, data window and bar size) count once, keeping the
  earliest; a run repeating an earlier test is not counted again (`this_run` 0) and its own Sharpe
  replaces the earlier one. Rows without a spec hash or symbol cannot be matched and each count.
- `trial_dsr` uses exactly the verdict's inputs below, so for a rule test with diagnostics it equals
  the verdict's `dsr`. The public expected-maximum and PSR functions compute the probability.
  Diagnostics and `spine.deflation` store the count, components, ledger rows and reader version;
  `family_trials` cites the recorded count. Missing ledgers count zero; unreadable ones fail with
  `LEDGER_UNREADABLE`, never a one-trial fallback. No diagnostics means `spine.deflation` is null.
- The verdict's `dsr` takes its variance from counted family Sharpes of the run's bar size only
  (daily on either calendar; another bar size's per-bar Sharpe is on another scale, so it counts in
  N but not in the variance) and this run's own OOS Sharpe, with N at least the family count.
  Sensitivity variants count in N but stay out of the variance: they are full-sample figures of
  neighbouring settings, another basis and strongly correlated, and would narrow the spread.
  Below 5 comparable trials (distinct same-bar-size family tests with a Sharpe, this run included)
  the variance is the larger of the sample variance and the sampling variance of this run's
  per-bar Sharpe (the PSR's non-normal standard error, squared); from 5 the sample variance stands.
  `trial_basis` says in plain words when the count is the wider same-asset count of any
  rule, how many repeats were not counted and when the spread was floored. `dsr` also records
  `family_id`, `prior_sharpes`, `family_count`, `comparable_trials`, `repeats`, `spread_floored`
  and `deflation_rule` (`family-dedup-floor-2`, not part of the run id). A rule test reads the
  ledger once for both the verdict and diagnostics; an unreadable ledger stops `alpha validate`
  with `LEDGER_UNREADABLE` and its next step.
  `alpha validate` recognises existing spine families by registered rule strategy; other runs state
  `no ledger family: counted as one trial`. Re-running an existing run id reuses the family inputs
  in its manifest, never today's grown ledger. No ledger history or immutable run is rewritten.
- `alpha results show` adds the recorded count and live `family_counts` rows, outcomes and reader
  trials from the spine-only snapshot. Older runs have a null recorded count and an explicit reason.
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
