# ADR-0051: Glue rules for outside projects

**Status:** Accepted
**Date:** 2026-11-15
**Deciders:** AI build agents, under the owner's direction of 2026-11-15: "I want ti add more
robust repos that are built well and not vibe coded like mine and have the glue like we do with
qlib and rd agents it seems to work well.", and, after reading the study of candidates the same
day: "I approve adding and using more of your suggestions for the repos"

## Context

An **outside project** is any open-source library, engine or tool that ALPHA did not write.
**Glue** is the small amount of ALPHA code that connects one: it hands the project its inputs,
checks what comes back and records the result. The owner wants more of ALPHA's work done by
well-built outside projects and less by code written here, joined the way RD-Agent and Qlib
are joined, because that way has worked.

What worked with those two, read from the repository:

- **The real project, untouched.** RD-Agent is one upstream commit, checked file by file before
  Python loads any of it (`workers/rdagent/source_pin.py:verify_source`). Qlib is the published
  `pyqlib` package at one exact version (`workers/qlib/pyproject.toml`). Neither is edited.
- **Plugged in through its own settings.** ALPHA's judge reaches RD-Agent by naming ALPHA's
  classes in RD-Agent's settings, which is how RD-Agent expects to be extended
  ([ADR-0049](0049-alpha-judges-rdagent-factors.md)).
- **Its own install.** Each runs as a *worker*: a separate program with its own Python
  environment and its own lock file (the file that lists the exact version and checksum of every
  package). Work passes between ALPHA and the worker as plain files that both sides check
  ([ADR-0016](0016-isolated-qlib-worker.md)); `tests/unit/test_qlib_isolation.py` proves that no
  ALPHA package imports Qlib.
- **ALPHA keeps the verdict.** Qlib's predictions are replayed with costs by ALPHA, and
  RD-Agent's factors are scored by ALPHA; the engine's own report is never the result.

[ADR-0011](0011-evidence-gated-external-integrations.md) already says an outside project needs
evidence of a real gap before it is adopted. It lists what a proposal must record. It does not
say how an adopted project is joined, and each later record (0016, 0042, 0044, 0049) settled
that again for one engine. This record states the rules once, for every future session.

## Decision

Every outside project ALPHA adds or uses follows these rules. ADR-0011's checklist for a
proposal still applies; these rules say what to choose and how to join it.

1. **Prefer a proven library to hand-written code, when it closes a row or deletes code.** Name
   the row of the [production-scope checklist](../roadmap/production-scope.md) it closes, or the
   ALPHA file it lets us delete. *Reason: less code written here means less that can be wrong
   here; a library that does neither only adds weight.*
2. **Judge every candidate on five things: fit for a retail swing trader, upkeep, licence,
   dependency weight, and conflict with ALPHA's pins.** A *pin* is a version ALPHA has fixed, such
   as its Python, numpy and pandas. Popularity is not a reason. *Reason: a widely starred project
   can still be unmaintained, wrong for long holds and small size, or carry wrong numbers.*
3. **Never edit upstream code. Plug in through its public settings and APIs.** *Upstream* means
   the outside project's own source. *Reason: an edited copy can no longer be upgraded or compared
   with what everyone else runs, and its bugs become ours.*
4. **Exact versions with checksums in the lock file; an upgrade is its own pull request with a
   side-by-side check.** Install only from the lock. The side-by-side check runs the same inputs
   on the old and new version and compares the outputs. Do not take a release in its first two
   weeks. *Reason: a result must be reproducible later, and a silent version change is a silent
   change to results.*
5. **Heavy or conflicting stacks run in their own pinned worker; light pure-Python libraries are
   imported inside one package.** Heavy means many dependencies of its own, a different Python,
   or versions that disagree with ALPHA's pins. *Reason: a worker keeps a conflict from spreading
   into ALPHA; one importing package keeps a light library easy to find and to remove.*
6. **One thin adapter per outside project, with a contract test and a smoke test through the
   installed `alpha` command.** The *adapter* is the one ALPHA module that talks to the project.
   The *contract test* checks the shape of what crosses the boundary; the *smoke test* runs the
   real installed program end to end on a small input. *Reason: one adapter is one place to fix
   and one place to switch the project off; the two tests show the join works for a real user.*
7. **ALPHA stays the judge and the record.** A number that decides anything comes from ALPHA's
   own tested code, or from a library call pinned by a *parity test* (a test that holds the
   library's answer equal to an independent, known-correct value). It is written to ALPHA's
   ledger with ALPHA's labels. *Reason: the owner must be able to trust one source for every
   number, and an outside report can change meaning between versions.*
8. **An upstream bug gets a workaround through the project's own settings, plus a written
   proposed upstream patch. Never a local fork.** The workaround and the proposed patch are
   written on the project's component page, so the workaround can be deleted when upstream
   fixes it. *Reason: a fork is a private copy nobody else tests.*
9. **Every engine gets a component page; every outside project gets a row in the register.**
   The pages are in `docs/reference/project/components/`; the register is
   [outside projects](../reference/project/outside-projects.md). *Reason: the owner and the next
   session must be able to learn what each project is for, and why, from the file system.*
10. **A library that replaces hand-written code must show equivalence first.** Run both on the
    same inputs and compare the values before the old code is deleted. A difference that exists
    by design (a different convention or default) is an owner decision, not a rounding note.
    *Reason: a swap that quietly moves a number is a loss of precision nobody chose.*
11. **Refuse a project when any of these holds:** it is not open source; it is unmaintained; it
    conflicts with ALPHA's pins and is not worth a worker; it does a job ALPHA must judge itself
    (a second backtest engine, a second record of experiments, a second scheduler); or it
    promises results rather than tools. *Reason: each of these either cannot be checked or
    replaces the part of ALPHA that does the checking.*
12. **DuckDB is a query tool over the files ALPHA already writes, never the store.** DuckDB is a
    database program that can answer a question across many files at once. It is opened in
    memory, pointed at the existing Parquet and ledger files, and closed. Bars, snapshots,
    ledgers and the point-in-time reader stay as they are. *Reason: snapshots work because a
    file's bytes never change and its checksum proves it; a database file changes on every
    write.*

Two rules ALPHA already had apply to every adapter and are restated here only by reference:
pandas stays at its named edges ([engineering rules](../reference/invariants/engineering.md#polars-by-default)),
and a library that fits on a whole series gets a look-ahead guard, as ALPHA's own indicators do
([research integrity](../reference/invariants/research-integrity.md#point-in-time-reads)).

## Where the repository differs today

The rules describe where the repository is going. Four things do not match them yet.

| Difference today | What closes it |
|---|---|
| Most main-install manifests give version ranges (`pandas>=2.0`); exact versions and checksums are only in `uv.lock`. | [Exact pins in the manifests](../roadmap/backlog/exact-pins-in-root-manifests.md) |
| NautilusTrader is imported directly by three packages, not run as a worker and not behind one adapter. | [Name where Nautilus may be imported](../roadmap/backlog/nautilus-import-boundary.md) |
| Kronos is a copy of two upstream files inside `alpha_forecast/_vendor`, with a documented import rewrite, because upstream publishes no package ([ADR-0008](0008-vendored-kronos-and-alpha-forecast-layer.md)). | [Re-check the Kronos copy](../roadmap/backlog/kronos-vendored-copy-recheck.md) |
| `workers/rdagent` has no automatic checks on a pull request, so rule 6 is unmet for the core engine. | [Gate coverage for workers/rdagent](../roadmap/backlog/gate-coverage-rdagent.md) |

Rule 8 had no written home and no worked example before this record; it is now written here.

## Options considered

| Option | Verdict |
|---|---|
| Keep deciding the join again for each engine | Rejected: four records already repeat the same choices, and a new session cannot find them |
| Adopt popular projects as they are suggested | Rejected by ADR-0011 and by the owner's own wording ("built well") |
| Write everything in ALPHA | Rejected: it is the opposite of the owner's direction and of the thin-out |
| **One set of rules and one register** | **Chosen** |

## Consequences

- A session that wants to add a library has one page to follow and one table to update. A
  project already judged is not judged again without new facts.
- The five libraries the owner approved (statsmodels, arch, ruptures, DuckDB, and
  pandas-datareader for one data set) are not added by this record. Each arrives in its own pull
  request with its adapter, its tests and the code it retires.
- Harder: an upgrade costs a pull request and a comparison, and rule 10 slows every swap of
  hand-written maths for a library.
- The four differences above stay visible on the roadmap until closed.
- The owner's two statements quoted in the header are cited here in plain text. The first is
  recorded in the owner decisions log by pull request 198, which is not merged yet; the second
  is not in the log yet.

## Implementation anchors

- `workers/rdagent/source_pin.py:verify_source`; `scripts/setup_rdagent.sh` (installs with
  `--require-hashes --no-deps`).
- `workers/qlib/pyproject.toml`, `workers/qlib/uv.lock`; `scripts/setup.sh` (`uv sync --locked`).
- `tests/unit/test_qlib_isolation.py`, `tests/unit/test_ml_contract.py`,
  `tests/unit/test_rdagent_foundation_contract.py`, `tests/smoke/test_rdagent_smoke.py`.
- `packages/alpha-validation/src/alpha_validation/tearsheet.py` (the one place the report
  library is imported).
- The register: [outside projects](../reference/project/outside-projects.md).
