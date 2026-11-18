---
owner: project layer
sources:
  - docs/reference/project/owner-decisions-4.md
verified: e3b0c44298fc1c14
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
