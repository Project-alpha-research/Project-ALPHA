# Live trading phase (private, single owner)

**Status:** Scoped
**Rough size:** XL

## Problem / why

The readiness checklist names a definite later phase in which ALPHA trades real capital for its
single owner. Nothing in the tree routes orders to a broker or venue today: paper paths are opt-in
and "no live-capital route ships" (README). The phase is unsized until the venue, instrument family
and limits are chosen.

## What "done" looks like

- A venue/broker adapter behind explicit credential boundaries.
- Order intent and lifecycle with idempotency and basic realistic execution.
- Position, cash and order reconciliation against the venue.
- Risk limits, kill/freeze controls and disconnect/restart recovery.
- Paper/shadow/fault qualification, then a separate limited-capital approval by the owner.
- The approval gate shows an evidence pack: the idea record, data description, every experiment
  id, the baseline, validation results, portfolio assumptions, known weaknesses and the verdict.
- Paper-phase rules: how long to paper trade and how many trades before judging; slippage and fill
  gaps against the backtest; a demotion trigger when live results fall well below validated ones;
  a cumulative-sum decay test; a daily signal health check.
- Risk controls: staged drawdown halts (day, week, peak), per-asset and per-sector caps, a limit on
  portfolio correlation, and a personal drawdown tolerance that is enforced mechanically.

## Dependencies

W17 (whole research process and paper boundary) for paper qualification; W14 for monitoring and
pause/restart; an owner decision on venue, instruments, limits and observation requirements. A new
ADR and threat/risk review (the crypto readiness plan lists live capital as explicitly deferred).

## Sources

- [Checklist: Definite later live trading phase](../../archive/research-notes/feature-readiness-checklist-2026-10-27.md#definite-later-live-trading-phase)
- [Checklist: Explicit exclusions and boundaries](../../archive/research-notes/feature-readiness-checklist-2026-10-27.md#explicit-exclusions-and-boundaries)
- [Checklist W17](../../archive/research-notes/feature-readiness-checklist-2026-10-27.md#w17-qualify-the-whole-research-process-and-paper-boundary)
- [Crypto operational readiness plan, deferral table](https://github.com/tradingsystem1880-eng/Project-ALPHA/blob/pre-thin-2026-11-14/docs/work/archive/2026-08/2026-08-30-crypto-operational-readiness/02-plan.md)
- [README: Implemented scope and limits](../../../README.md#implemented-scope-and-limits)

## More recovered from the second pass

- The owner's existing retail terminals and charting platform are candidate venues for the live phase.
- A retrain trigger for models when their out-of-sample score stays below zero for several periods.
- Alerts reach the phone in tiers (information, warning, critical); a missed heartbeat from a
  scheduled job raises an alert, so silent failure is caught. Related Dell tools to weigh: a job
  scheduler, backup, a change watcher on provider pages, a feed reader for the discovery queue.
