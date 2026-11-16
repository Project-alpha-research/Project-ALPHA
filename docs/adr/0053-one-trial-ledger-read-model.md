# ADR-0053: One trial ledger, read as one model

**Status:** Accepted
**Date:** 2026-11-16
**Deciders:** AI build agents, under the owner's direction recorded in
[ADR-0051](0051-glue-rules-for-outside-projects.md): use robust outside projects with small,
explicit connections. This implements the checklist row
[“Every test, tool and variant counted in one ledger”](../roadmap/production-scope-2.md).

## Context

Three records exist: the spine's `AlphaTrialV1` rows, RD-Agent factor V1/V2/V3 rows,
and preregistered `AlphaRuleTrialV1` rows in the same external RD-Agent file.
They cannot previously be read together. Rewriting is refused: append-only rows are evidence
and their hashes are cited. A query engine must not become another source of truth.

## Decision

Writers remain unchanged. `spine/trial_record.py:TrialRecord` is a frozen common record;
`spine/trial_reader.py:read_ledgers` maps known rows and retains unknown rows with their source,
line and reason. It reads bytes once under an existing shared lock, opening the lock read-only;
no lock or ledger is created. An unfinished last line is unknown. Missing sources are reported.
The spine source is `<home>/ledger/trials.jsonl`; an explicit RD-Agent path overrides the
absolute path in `<home>/ledger/sources.toml`.

Every record has identity, family, provenance, windows, recorded measures, evidence reference,
labels and timestamp basis. RD-Agent timestamps use only a valid date prefix in the run id.
There are exactly six outcomes:

| Row kind | Stored status | Outcome |
|---|---|---|
| Spine rule test | `error` label | error |
| Spine rule test | A, B | supported |
| Spine rule test | C | inconclusive |
| Spine rule test | D, F | rejected |
| Spine rule test | null verdict without error | recorded |
| Other spine kinds | any verdict | recorded |
| Factor | CANDIDATE | supported |
| Factor | SCREEN_FAIL, REPLAY_FAIL, FAST_ONLY | rejected |
| Factor | DEGENERATE, LOOKAHEAD | invalid |
| Factor | FAILED, ERROR | error |
| Factor | IMPORTED, REPEAT | recorded |
| Rule family | SUPPORT | supported |
| Rule family | CONTRADICTION | rejected |
| Rule family | INSUFFICIENT | inconclusive |
| Rule family | INVALID | invalid |

Unknown statuses are unknown rows, never guessed outcomes. FAST_ONLY is rejected under
[ADR-0050](0050-swing-clocks-in-the-factor-judge.md): only a swing-clock pass is a candidate.
Spine rows retain their labels. RD-Agent labels retain exploratory, admission, prior exposure,
survivorship, repeat and imported disclosures in that order when applicable.

`spine/trial_query.py` is the only DuckDB adapter: lazy import, `:memory:` connection,
external access disabled, registration of the Arrow table, and fixed named SQL questions
with bound values. It exposes no free SQL or file reader. `alpha ledger` supplies summary,
list, show, families and query commands; evidence checks hash the referenced file now.

`trials_for_deflation` supplies the count for the later deflated-Sharpe integration. Spine
rule counts exclude repeat and error labels; tools and setup searches do not count.
Rule-family counts count rows. Factor counts reuse `trial_family` (distinct code/clock pairs,
excluding repeats) plus every unknown RD-Agent row. `all_trials` sums those family counts and
adds every unknown row from either source; thus an unknown RD-Agent row also contributes to
the factor family's conservative count. Recorded family sizes remain separately visible.
An unmapped RD-Agent row of a factor schema (a status the reader has no mapping for yet) is fed
to the writer's own `trial_family` counter, so the factor count is never below the family size
the writer recorded; any other unknown RD-Agent row adds one. Real data on 2026-11-16: two V3
rows with status `SPREAD_FAIL` (a writer not yet on main) are shown unknown and counted.

## Options refused

- One rewritten file: breaks cited hashes and replaces historical evidence.
- A SQLite store: a second source of truth and a synchronization obligation.
- Free SQL: could read arbitrary paths; named bound questions suffice for this view.

## Consequences

A new schema needs a mapping or appears as unknown, with its attempt still counted.
The view does not grant research or owner authority. Switching the spine's DSR count is a
follow-up; this change does not alter any writer or existing statistical calculation.
The installed-command smoke check is written but awaits execution outside the build sandbox.

Implementation contracts: `tests/unit/test_trial_record.py`, `test_trial_reader.py`,
`test_trial_query.py`, `test_ledger_cmds.py`, and
`tests/smoke/test_ledger_smoke.py::test_ledger_reads_rule_and_factor_trials`.
The operational rules live in [trial ledger invariants](../reference/invariants/cli-trial-ledger.md).
