---
owner: command line trial ledger read model
sources:
  - apps/alpha-cli/src/alpha_cli/spine/trial_record.py
  - apps/alpha-cli/src/alpha_cli/spine/trial_reader.py
  - apps/alpha-cli/src/alpha_cli/spine/trial_query.py
  - apps/alpha-cli/src/alpha_cli/ledger_cmds.py
  - tests/smoke/test_ledger_smoke.py
verified: 0000000000000000
---

# One trial ledger invariants

`alpha ledger` reads the spine ledger and the external RD-Agent factor/rule ledger as one
model. [ADR-0053](../../adr/0053-one-trial-ledger-read-model.md) owns the outcome mappings and
counting decision. Options are in the [command reference](../commands.md#alpha-ledger).

## Sources and snapshots

- The spine source is `<home>/ledger/trials.jsonl`. `--rdagent-ledger PATH` overrides
  `[rdagent] factor_ledger = "/absolute/path"` in `<home>/ledger/sources.toml`.
  With neither, only the spine source is configured. Invalid TOML or configuration produces
  `LEDGER_SOURCE_INVALID`; configured files that do not exist are reported as missing.
- Read each file's bytes once. Acquire a shared `flock` only when its `.lock` exists, opened
  `rb`; never create directories, files or lock files. No writer or historical row is changed.
- Each mapped record carries an absolute source path and one-based line. Raw rows are retained
  in the snapshot for `show`; they are not reread from a possibly newer file.
- Non-object JSON, missing required mapping fields, unknown schemas/statuses and malformed
  field values become unknown rows with a reason. An incomplete final line is reported as
  `incomplete last line (a writer may be mid-append)`. File access failures fail loud.
- Every command reports sources and unknown rows in JSON. Human output includes unknown counts
  and reasons and ends with `Read-only view; the ledgers themselves are unchanged.`

## Families and queries

- Families remain separate: spine rule, tool, setup and other families, `rdagent-factors`,
  and `rule:<family_id>`. Keep recorded family size separate from the reader count.
- `family_counts` reuses the existing RD-Agent `trial_family` function. Unknown RD-Agent rows
  contribute conservatively even if there are no mapped factors. `all_trials` adds all
  unknown rows again to the sum of family counts, as specified by ADR-0053.
- `trials_for_deflation` exposes family count, all-trials count and basis. Existing DSR callers
  are unchanged; wiring them to this seam is a follow-up.
- DuckDB is imported only for a query, connects to `:memory:` with external access disabled,
  and receives a Polars frame converted to Arrow. There is no database file or SQL file read.
- Questions are `by-family`, `by-outcome`, `by-asset`, `by-month`, `asset-history`,
  `family-trials`, `top-measure` and `repeats`. Bind values with `?`; reject unknown questions
  with `UNKNOWN_QUESTION` and missing/unlisted parameters with `BAD_PARAMETER`.
- Limits are 1–200, default 50. Top measures exclude nulls; p and q sort ascending and the
  other allowed measures descending. Undated rows group under `unknown` for by-month.

## Evidence checks

- Spine evidence resolves under the home directory. Factor evidence resolves under the
  RD-Agent file's grandparent, then run id and evidence path. Rule evidence requires a unique
  match one study directory below that root. Paths escaping the root and ambiguous matches fail.
- `show` reports presence, current SHA-256 and match to the recorded digest; match is null
  when no digest was recorded. Missing evidence with a recorded digest does not match.
- These checks describe recorded evidence only; no test or research conclusion is recomputed.
