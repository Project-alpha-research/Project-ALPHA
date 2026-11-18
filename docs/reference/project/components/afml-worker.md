---
owner: project layer
sources:
  - workers/afml/CONTEXT.md
  - workers/afml/README.md
  - docs/adr/0054-afml-worker.md
verified: 3854309f04792fb6
---

# AFML worker

A separate program that runs methods from Marcos López de Prado's textbook *Advances in
Financial Machine Learning* through two independent open libraries, RiskLabAI and quantowl, and
only hands a number back when both agree. Today `alpha labels` uses it to label what happened after an event, weight overlapping labels
and report which factors the labels lean on; (target,
stop or time limit first) and measures how much overlapping labels repeat the same days.

## Why it exists

A swing trade lasts days, so the outcomes of nearby signals share the same price moves. Counting
them as independent overstates the evidence, and labelling them on closes alone ignores stops
that trigger inside a day. ALPHA had neither a label generator nor overlap weights. The owner
decided these methods come from community libraries rather than new ALPHA code; they need a
statsmodels version and numba that ALPHA's main install does not take, so they run in their own
worker ([ADR-0054](../../../adr/0054-afml-worker.md), glue rules in
[ADR-0051](../../../adr/0051-glue-rules-for-outside-projects.md)).

## Its job in the research loop

Steps 4 and 6 of the [research loop](../overview.md#the-research-loop): it turns events into
labelled outcomes for building and judging an idea, and weights them by how much they overlap.
Its output is advisory; ALPHA's own code decides what a label means.

## Intended design

- Its own install and lock; no ALPHA package imports it, and it imports none.
- Two libraries side by side; a value both implement must agree to 1e-10 or the worker stops.
- Labels default to ALPHA's convention: highs and lows, entry at the next open, a bar touching
  both barriers scored stop-first with the optimistic reading kept beside it.
- Nothing fitted on the whole sample; every look-ahead-sensitive function has a truncation test.
- Also in the worker: purged splits by label end time with a brute-force leak checker,
  fractional differencing with d chosen on training data only, factor importance on those
  purged folds (a report for RD-Agent's factors), and second opinions on PSR, DSR and PBO.

## What is real today

See the capability below on [STATUS.md](../../../../STATUS.md).

## Where it lives

- **Workspaces:** `workers/afml`
- **Capabilities:** `afml-labels-and-weights`, `afml-factor-importance`, `afml-purged-cv`, `afml-fracdiff`,
  `afml-stats-second-opinion`
- Code: [`workers/afml/`](../../../../workers/afml/README.md).
- Tests: `workers/afml/tests/`; CI job `afml-worker`.
- How to change it: [workers/afml/CONTEXT.md](../../../../workers/afml/CONTEXT.md).
- **Plan:** the textbook-methods rows of [stage 9](../../../roadmap/production-scope-2.md#9-rd-agent-and-qlib-engines) of the checklist.
- Decision records: [ADR-0054](../../../adr/0054-afml-worker.md).

## Decisions and open questions

- No owner decision about this part is in the [owner decisions log](../owner-decisions.md) yet.
  The barrier convention (highs and lows, stop-first on an ambiguous bar) was ruled at owner
  level by the orchestrator on 2026-11-16 and is recorded in ADR-0054.
- `alpha labels barrier|weights` calls the worker. ALPHA's own `barrier.py` and the worker's
  high/low labels agreed on every SPY and BTC daily event (2026-11-16); the one designed difference
  is a bar that opens beyond a barrier, which the worker decides by its open.

## Never

- Never edit either library's code, and never add them to ALPHA's main install.
- Never offer a value only one library computes without a hand-checked parity test.
- Never present a label, weight or count from this worker as a profit or a verdict.
- The rules: [AFML worker](../../invariants/workers.md#afml-worker).
