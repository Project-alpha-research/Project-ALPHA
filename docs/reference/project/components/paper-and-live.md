---
owner: project layer
sources:
  - docs/reference/project/owner-decisions.md
verified: f23dc19226088ee7
---

# Paper and live trading

The route from a strategy the owner has promoted to trading it: first on real data on the Mac,
then forward paper tracking (`alpha follow`, no broker), and in a later phase live capital.

## Why it exists

The owner's strategies "will eventually have live capital deployed"
([owner decisions](../owner-decisions.md#2026-11-14-precision-and-live-capital)). Each phase must
prove itself before the next, and the owner approves each move.

## Its job in the research loop

Step 8 of the [research loop](../overview.md#the-research-loop), after the owner has promoted a
strategy. Forward paper records never become research evidence.

## Intended design

- The [phases](../overview.md#phases): Dell on synthetic data, then the Mac with real data, then
  paper, then live, each gated by the owner.
- There is no broker paper trading. Forward paper tracking is `alpha follow` (no broker).
- Live trading is a planned phase with its own decision record, risk review, broker adapter,
  reconciliation, risk limits and kill controls ([backlog item](../../../roadmap/backlog/live-trading-phase.md)).

## What is real today

See the capabilities below on [STATUS.md](../../../../STATUS.md). No code path can place a live
order today.

## Where it lives

- **Workspaces:** none of its own; forward tracking is `alpha follow` in `apps/alpha-cli`.
- **Capabilities:** `mac-real-data`
- Plans: the `plans` of each capability above in `docs/roadmap/capabilities.toml`.
- Backlog: [live trading phase](../../../roadmap/backlog/live-trading-phase.md).
- Runbook: [local operations](../../../operations/README.md).
- Decision records: [ADR-0012](../../../adr/0012-operational-paper-sessions.md),
  [ADR-0017](../../../adr/0017-authoritative-daily-data-and-broker-paper-boundary.md),
  [ADR-0031](../../../adr/0031-provider-readiness-and-paper-acceptance-v2.md).
- **Plan:** [stage 11](../../../roadmap/production-scope-3.md#11-paper-and-live) of the checklist.

## Decisions and open questions

- Dell now, Mac later ([log](../owner-decisions.md#2026-11-14-dell-now-mac-later)). Triage card 13
  (running ALPHA on the Mac with real data): KEEP, 2026-11-14 under the owner's delegation; its two
  plans are merged into one.
- Decided: live trading is deferred until the whole system works and has shown it can find an edge.
  Do not ask for a broker, instruments or risk limits yet
  ([log](../owner-decisions.md#2026-11-14-live-trading-is-deferred)).


## Never

- Never add a code path that places live-capital orders before the owner approves the live phase
  and its decision record exists.
- Never count a paper session as validation evidence.
- The rule: [no live capital](../../invariants/research-integrity.md#no-live-capital).
