---
owner: project layer
sources:
  - docs/reference/project/owner-decisions.md
verified: e3b0c44298fc1c14
---

# Owner decisions log, volume 4

Continues the [owner decisions log](owner-decisions.md), [volume 2](owner-decisions-2.md) and
[volume 3](owner-decisions-3.md); the rules for entries are in the first. New entries are appended
at the end of this file.

## Entries

### 2026-11-16 RD-Agent judge: spread check, idea families, universe file, call time limit

- **Said:** exact words not recorded: the owner delegated these decisions; they were decided by
  the orchestrating AI agent under the owner's delegation, 2026-11-16.
- **Context:** the 2026-11-16 health check of RD-Agent's factor loop: 15 of 18 replayed factor ×
  clock trials lost money before costs although they passed the rank screen; the proposer was told
  only "failed the replay"; the universe was hard-coded; model calls hung for minutes.
- **Decided:** (1) add a check before the replay that the top third the factor would hold beats the
  bottom third, before costs, at each clock, without loosening anything; (2) tell the proposer each
  rejected factor's spread, thirds, turnover and cost, group the whole ledger by idea family, and
  tell it to leave a family after 3 failed near-variants (configurable); (3) make the universe,
  calendar and year length configuration, widen crypto only by a point-in-time liquidity rule over
  coins already in the store, and wire US stocks if the Alpaca store can support thirds; (4) a
  180-second limit per model call with one bounded retry, counted against the caps; (5) leave the
  60-call, USD 10 per run and USD 50 per month caps and what counts toward them unchanged, and show
  paid model calls and free local embedding calls separately on the run receipt. Corrected the
  same day: a factor stopped by the spread check is still a trial, counted in the Deflated Sharpe
  exactly as before the check existed; long embedding inputs are chunked at sentence ends and
  averaged, never truncated, and a memory entry whose embedding still fails is left out, counted
  and reported on the receipt.
- **Left to the owner:** whether free local embedding calls should count toward the 60-call cap.
- **Governs:** [RD-Agent](components/rd-agent.md);
  [ADR-0055](../../adr/0055-spread-check-family-brief-and-universe-file.md).
