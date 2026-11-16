# Textbook machine-learning methods in their own pinned worker

**Status:** Idea
**Rough size:** L

## Problem / why

A study made on 2026-11-16 (kept in the owner's folder, outside git) compared ALPHA with the
methods of a well-known financial machine-learning textbook. ALPHA has some of them (deflated
Sharpe, overfitting probability, combinatorial splits, one barrier score per trade) but not the
ones that make multi-day labels honest. Two maintained libraries were found that implement the
book with tests: RiskLabAI (widest cover) and quantowl (an independent second opinion). This
reverses two older register verdicts, which were based on facts the study corrected (see the
register rows for RiskLabAI and mlfinlab). Nothing is approved yet: the owner decides.

Planned in waves, each closing a checklist row and each checked against a hand-made version:

1. Sample uniqueness, time-decay weights, sequential bootstrap: how much evidence is the same
   few days counted again (closes the overlapping-windows row in stage 5).
2. Triple-barrier labels, meta-labels, an event filter: a label generator ALPHA lacks.
3. Purged k-fold and combinatorial splits using each label's end time (ALPHA's purge assumes
   one-day labels).
4. Fractional differentiation, with the order fitted on the training span only.
5. Purged feature importance for RD-Agent's factors (the unpurged variants are avoided).
6. Second-opinion checks of ALPHA's own deflated Sharpe and overfitting numbers, plus minimum
   track-record length.
Later waves: trend-scanning labels, bet sizing, structural breaks, liquidity estimates, the
haircut for many tests; then hierarchical baskets and denoised covariance.

## Where it would live

A new worker, `workers/afml` (own install and lock, like Qlib), called by `alpha`; ALPHA keeps
the ledger and the judging, never the worker. A shared set of parity fixtures checks every
method against a hand-made version before it is trusted.

## What "done" looks like

Wave 0 (worker, lock, thin adapter, `CONTEXT.md`, parity fixtures) and wave 1 merged, each with
its parity test, and the matching checklist rows moved to Unproven or Working.

## Dependencies

- Owner approval of the worker. Open owner question: is a barrier touched by the bar's high and
  low (ALPHA today) or by the close only (the libraries)? ALPHA's convention stays meanwhile.
- Never: tick bars, order-flow toxicity or price-impact lambdas; they need ticks
  ([never high-frequency](../../reference/project/owner-decisions-2.md#2026-11-14-never-high-frequency-trading)).
- Known traps to test for: choices made on the full sample, overlapping labels, embargo units.

## Sources

- [Outside projects register](../../reference/project/outside-projects.md#judged-in-the-november-follow-up-studies)
- [Checklist stage 5](../production-scope-2.md#5-overfit-tests)
