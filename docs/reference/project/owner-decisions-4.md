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

### 2026-11-18 Working order: golden paths 1 and 2 reach the screen first

- **Said:** exact words not recorded: this is the orchestrating AI agent's working order, set under
  the owner's standing authority. It is the orchestrator's default, and the owner can reverse it.
- **Context:** the owner's [2026-11-14 entry](owner-decisions-2.md#2026-11-14-first-goal-one-real-rd-agent-loop)
  put one real RD-Agent loop first; the owner's [2026-11-15 entry](owner-decisions-3.md#2026-11-15-build-the-thin-spine-clean-then-switch-over)
  put the golden paths in the order 1 rule test, 2 chart setup, 3 factor mining. The two disagree,
  and recent work followed the first. An alignment audit on 2026-11-18 found that about half of
  recent pull requests went to the RD-Agent judge. This entry does not rewrite either past decision.
- **Decided:** (1) golden paths 1 and 2 are brought to a Workstation screen first; (2) until then,
  RD-Agent work is limited to crash fixes and one supervised job; (3) the order of work is:
  1. the Setup Lab screen (path 2);
  2. the rule-test report screen with the benchmark, and `alpha test` itself proven end to end;
  3. the short side and risk-per-trade sizing, in rule tests and setup trades;
  4. the Ledger screen, and lessons actually written;
  5. the RD-Agent loop as a supervised `alpha` job with a scripted smoke test;
  6. the AI app and phone access;
  7. the platform journey check;
  8. Qlib in a real path;
  9. the owner's setup library and the daily scan, with export;
  10. one backtest engine per kind of test.
  The roadmap data has no field for an order (the status page lists the backlog alphabetically),
  so this list is the one place the order is recorded.
- **Left to the owner:** reverse or reorder any of it.
- **Governs:** [overview](overview.md#the-target-shape);
  [checklist](../../roadmap/production-scope.md); [RD-Agent](components/rd-agent.md).

### 2026-11-18 Three RD-Agent decisions the orchestrator made, recorded after the fact

- **Said:** exact words not recorded: each was decided by the orchestrating AI agent under the
  owner's standing authority, and each is reversible by the owner.
- **Decided:** (1) paid embeddings, with money caps only (2026-11-17): explicitly configured
  provider embeddings reserve and settle token-priced money and share the 2,000-attempt guard with
  free local ones; call and dollar caps are unchanged
  ([ADR-0055 amendment](../../adr/0055-spread-check-family-brief-and-universe-file.md)); (2) a
  factor that reads funding rates is checked for 80% coverage against the coins that have a funding
  rate that day, not against every coin; every other rule is unchanged (pull request 252);
  (3) the shortlist label is bookkeeping only: it marks a factor that passed all but the
  many-tries correction, and is not a pass, a candidate or evidence of profit (pull request 253).
- **Governs:** [RD-Agent](components/rd-agent.md).

### 2026-11-18 Open owner decisions, listed in one place

- **Said:** exact words not recorded: the orchestrating AI agent listed these open questions; none is decided.
- **Context:** these are waiting for the owner. The first five are on the status page's
  "Waiting for your decision" list (the [capability map](../../roadmap/capabilities.toml), cards
  N1 to N5); the audit questions are not copied here.
- **Left to the owner:** (N1) confirming shortlisted factors once on the reserved data, which has
  ten slots and each use is permanent (not built); (N2) the RD-Agent idea-family failure limit:
  three near-copies in one round closed a family ([ADR-0055](../../adr/0055-spread-check-family-brief-and-universe-file.md));
  (N3) whether RD-Agent research should move toward stocks and the owner's own setups; (N4) making
  the Qlib v3 feature recipe the default ([ADR-0042](../../adr/0042-qlib-worker-delegates-data-layer-to-upstream.md));
  (N5) when to resume Workstation screen work. The open audit questions are in
  [production-scope part 3](../../roadmap/production-scope-3.md#questions-from-the-file-system-audit).
- **Known defect:** RD-Agent's run 5 stopped mid-run with a crash; pull request 254 fixed it, and it
  is not yet proven in a real run. The status page's defect list only holds failing smoke checks,
  so it is recorded here instead.
- **Governs:** [RD-Agent](components/rd-agent.md); [Qlib](components/qlib.md);
  [Workstation](components/web-workstation.md).
