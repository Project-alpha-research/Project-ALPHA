---
owner: project layer
sources:
  - docs/reference/project/owner-decisions-4.md
  - docs/reference/project/owner-decisions-5.md
verified: 96a26a900543e934
---

# Ideas and things considered

One line per idea weighed, with its date and status, so a later agent does not re-argue it. The
owner wants the file system to carry plans, reasons, things considered and ideas
([owner, 2026-11-18](owner-decisions-4.md#2026-11-18-what-the-owner-said-about-the-purpose-of-alpha)).
Decisions the owner made are in the [decisions log](owner-decisions.md); add a line here when
something is considered, rejected or left open.

## Entries

| Date | Idea | Status | Why |
|---|---|---|---|
| 2026-11-17 | Judge remedy: relax the many-tries correction (deflation) | Rejected | Lets adaptive noise through |
| 2026-11-17 | Judge remedy: test at family level | Not simulated | Gameable by how families are drawn |
| 2026-11-17 | Bybit funding-rate data for factor inputs | Rejected | Too thin and survivors only; Binance used instead |
| 2026-11-17 | Binance open interest for factor inputs | Deferred | Starts December 2021 and is a long download |
| 2026-11-18 | Full bypass of the Codex build sandbox | Rejected | Risk of exposing keys; a limited widening was approved |
| 2026-11-18 | One backtest engine per kind of test | Open | Needs a side-by-side check before duplicates retire |
| 2026-11-18 | Qlib used in a real research path | Open | Installed in its worker; no real path uses it yet |
| 2026-11-18 | One data health report: adjustments, timestamps, gaps, survivorship | Step 1 built | `alpha data health` (PR #278); not yet attached to runs |
| 2026-11-18 | Break-even cost: the cost at which an edge vanishes | Built | PR #277; toolbox entry `costs.break_even`; older runs keep net only |
| 2026-11-18 | RD-Agent writes its own statistical tests | Not recommended | Marks its own homework; [entry][own-tests] |

## Open questions

Not yet decided; each needs the owner or a measurement before it is built.

- **Reserve policy for rule tests and setups.** Today `alpha test` and `alpha setup` hold nothing back
  and only RD-Agent's judge locks 2024 onward. Options: one held-back period for everything, a held-back
  tail chosen per idea, or the status quo with labels. See the [toolbox](components/toolbox.md).
- **Near-duplicate ideas.** Should two near-identical ideas count once toward a family's failed tries?
- **Minimum track record.** The validation package has no function for the shortest history that
  supports a given Sharpe ratio.

[own-tests]:
  owner-decisions-5.md#2026-11-18-rd-agent-may-choose-tests-but-not-write-them-recommendation-not-yet-confirmed
