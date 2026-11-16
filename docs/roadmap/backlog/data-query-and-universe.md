# Data questions from the November repository studies

**Status:** Idea
**Rough size:** M

## Problem / why

Plans and rules from two private studies (2026-11-15/16) that are not yet in the data layer:

- DuckDB (pull request 213) first step: a small module with read-only views over trials, bars
  and context, used by `alpha context`, with two tests and a data-layer note.
- One ledger shape with `kind` and `family` fields, so trials can be counted across the rule
  tests, RD-Agent and the parameter grid in one query.
- As-of joins match on the date a value became known; a rule is needed for values stamped at
  the same instant, with a poisoned-future test.
- Factor series (Fama-French) are labelled "as downloaded on" their date.
- Survivor-free universes: store index membership as a small checked file and label the bias;
  full delisted stock history is a paid Mac-phase item.
- No maintained event-study library exists; keep ALPHA's event study and build the
  random-date comparison from statsmodels and arch.
- The HTML performance report could be dropped once the Results screen shows all of it.
- Suggested order: the free data adapters first (filings, crypto bulk files), then lifelines,
  then the rest as their rows are built.
- Thinning comes from deleting old lanes; the studies estimate the libraries remove about 840
  lines of hand-written maths.

## Where it would live

`packages/alpha-data`, `apps/alpha-cli` (`alpha context`), the trial ledger.

## What "done" looks like

Each point built and its checklist row moved, or dropped by the owner.

## Dependencies

Pull request 213 (DuckDB, lifelines).

## Sources

- [Checklist stage 2](../production-scope.md#2-data-and-context)
- [Outside projects register](../../reference/project/outside-projects.md)
