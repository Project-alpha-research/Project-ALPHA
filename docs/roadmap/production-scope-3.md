---
owner: status page and roadmap
sources:
  - docs/reference/project/owner-decisions-3.md
verified: e3b0c44298fc1c14
---

# Production-ready scope, part 3: screens to hygiene, lost features, questions

The last part of [the checklist](production-scope.md), after [part 2](production-scope-2.md).
Reading a row is explained in the first part.

## 10. Screens

Every result visible in the Workstation, in a quant style, with text.

| Capability | State | Where | By | Source |
|---|---|---|---|---|
| The Workstation opens in a browser | Working | `alpha-web` | Now | [ui] |
| Setup Lab screen: every setup match on the chart, what followed, the trade study (a screen is being built) | Missing | `alpha-web` | Path 2 | [ui] |
| Idea screen: spec, clocks, source card, match gallery | Missing | `alpha-web` | Path 2 | [ui] |
| Results screen: annotated equity against benchmark, overfit tests, labels | Unproven | `alpha-web` report: rule-test section built; benchmark not yet drawn on the chart | Path 1 | [ui] |
| Trail screen: the reasoning from observation to next step | Missing | `alpha-web` | Path 1 | [partner] |
| Ledger screen: every idea tried, counts, lessons, RD-Agent runs | Missing | `alpha-web` | Path 1 | [ui] |
| Data screen: what is stored, coverage, quality | Unproven | `alpha-web` | Path 1 | [ui] |
| Research loop screen: Learn, Live and Findings views | Missing | prototype only | Path 3 | [style] |
| RD-Agent results readable in the Workstation | Unproven | `alpha-web`: read-only panel built; browser and real-run check pending | Path 3 | [ui] |
| Quant style: dense, restrained, light charts with arrows, always with text | Missing | `alpha-web` figures | Path 1 | [style] |
| Short view first, full detail one tap away | Missing | `alpha-web` | Path 1 | private |
| Context on the chart: state known on the day, rumour and fact marks | Missing | `alpha-web` | Later | private |
| Payoff picture for an idea expressed as an option | Missing | `alpha-web` | Later | private |
| The screens opened from a phone over private remote access | Missing | Dell setup | Path 1 | [spine] |
| Chat panels and demo views folded away once their content shows elsewhere | Missing | `alpha-web` | Later | [grade] |
| Pages fit a phone screen without sideways scrolling | Missing | `alpha-web` menu bar | Path 1 | [ui] |
| The owner's terminal-style screen mock-ups kept as a design reference beside the built screens | Missing | `docs/assets`; [note](backlog/rescued-partner-ideas.md) | Later | private |
| Signals and indicators handed to the owner's own charting platform, so the owner can keep the final call | Missing | `alpha-web`; [note](backlog/workstation-ui-ideas-from-owner-references.md) | Later | private |
| Further screen ideas from the owner's references: event bands, card gallery, model cards, explorers | Missing | `alpha-web`; [note](backlog/workstation-ui-ideas-from-owner-references.md) | Later | private |

## 11. Paper and live

The one approval gate, practice trading, then live trading in a later phase.

| Capability | State | Where | By | Source |
|---|---|---|---|---|
| One approval gate before paper or live, showing trial count and labels | Missing | `alpha-cli` | Phase | [thin] |
| An approval survives comment-only edits and dies on any logic change | Unproven | `alpha-research` | Phase | [struct] |
| Paper trading: local crypto practice account or a broker practice account | Unproven | `alpha-cli` paper | Phase | [status] |
| Separate alerts while trading: data, execution, exposure shift, performance | Missing | none yet | Phase | private |
| Live trading: broker link, reconciliation, risk limits, kill switch | Missing | backlog | Phase | [live] |
| Confirmation on the Mac with a paid, authoritative data source | Unproven | `alpha-data` | Phase | [mac] |
| A set response to each failure while trading; a pause never changes the strategy | Missing | none yet | Phase | private |

## 12. Health and hygiene

Keeping the project tidy, honest and never a mess.

| Capability | State | Where | By | Source |
|---|---|---|---|---|
| Weekly automatic health check that opens small clean-up pull requests | Working | scheduled task | Now | [health] |
| One gate for every change: look-ahead guards, statistical oracles, repeatable runs | Working | `scripts/`, `tests/` | Now | [precise] |
| File system that says what each part is for, updated with every change | Working | `docs/reference` | Now | [files] |
| Generated status page of what works | Working | `STATUS.md` | Now | [mess] |
| Results on free data labelled not yet confirmed | Working | `alpha-data` | Now | [free] |
| Old lane deleted when its golden path works; at most two streams in flight | Missing | whole repository | Path 1 | [spine] |
| Weekly mutation sweep passing | Missing | backlog | Later | [status] |
| Backup and restore of stored data and results | Missing | backlog | Later | [status] |
| Never high-frequency trading: nothing built for ticks, order books or speed | Working | scope rule | Now | [no-hft] |
| Every capability traced to a checklist row, every command to a capability | Working | [trace](capability-trace.md); contract test | Now | [files] |
| Stale branches listed and removed with the owner's sign-off | Missing | [health plan](health-plan.md) | Later | [mess] |
| Changelog generated from pull requests, or dropped | Missing | [health plan](health-plan.md) | Later | [mess] |
| A fresh agent's navigation measured: bytes read and the right answer | Missing | [health plan](health-plan.md) | Later | [files] |
| Nightly list of code that nothing calls, on the status page | Missing | [health plan](health-plan.md) | Later | [mess] |

## Lost-feature check

What was removed between the tag `pre-thin-2026-11-14` and today (492 files), and in the
clean-up of the two days before it. Everything removed can still be read at that tag.

| Removed | Files | What happens to it | Covered by |
|---|---|---|---|
| Agent benchmark tool (`tools/alpha-eval`) and its rules, tests, results | 147 | Rebuild slim as the platform journey check (stage 8) | [slim] |
| Build history: task folders, old records, audits, specs, archives | 342 | Dropped; the owner's research notes were restored | [thin] |
| Plan-file test, judge schema, work-in-progress limit file | 3 | Dropped with the folders they served | [thin] |
| QuantPad data command, adapter and archive code (before the tag) | 3 | Dropped; old registered rows stay readable | [quantpad] |
| Second copy of the paper-download code (before the tag) | 1 | Nothing lost; one copy remains | [delegate] |
| Delivery-task pilot (before the tag) | - | Replaced by the hand-off tool | [delegate] |
| Atlas code map: graph, viewer, diagrams (before the tag) | 77 | Replaced by the file system; see the flag below | [files] |

No capability a user could run was removed without a covering decision. Two things need the
owner's eye, because nothing stands in their place today:

- **Whole-platform evaluation.** The benchmark is gone and its slim replacement is not started.
  Until it exists, nothing scores whether the AI partner finds a planted cause by itself.
- **A visual code map.** Atlas was retired by a build decision record
  ([ADR-0040](../adr/0040-one-file-system-atlas-retired.md)), not by an entry in the owner's
  log. The file system replaced it for agents; the owner-facing part, "how this was computed"
  on a screen (stage 7), is Missing. The owner has since said that part is enough
  ([answers][answers], question 5).

Cuts that are planned but not made yet. Each keeps its capability in a row above:
the staged research cases (to the one gate), the in-product assistant and demo panels (folded
away only when their content shows elsewhere), the parameter grid (into variants that are
counted), the old daily-rule study lane (into Path 1), and the literature worker (into a thin
feeder). Rules, scans and patterns are reshaped into the Setup Lab, never cut: they are the
only route to "show every match first".

Made on 2026-11-15 with Path 1: the staged lane's instruction files (six stage files and its
routing skill) were replaced by the research playbook, tool cards and six skills. The lane's
commands, screens and protocol library are untouched; the stage files can be read at commit
`0c8b0535`.

## Questions put to the owner

The owner answered all five on 2026-11-15; the answers are in the [decisions log][answers].

1. **Data that costs money or needs an account.** Options quotes, flow data, news text and
   company fundamentals are marked Later. Must they work before ALPHA counts as production
   ready, or are they tracked and added when a study needs them?
2. **Macro data key.** The free macro source needs a key that only you can create. May the
   macro rows wait for it?
3. **In-product assistant.** Chat now lives in Claude or ChatGPT. Remove the assistant panel
   once the Trail screen exists, or keep it?
4. **Prop-firm check.** Keep it as an optional tool, or drop it?
5. **Code map.** Is "how this was computed" on each finding enough, or do you want a picture
   of the whole code back as well?

## Questions from the file-system audit

Raised on 2026-11-16 by the audit; not yet answered. Each blocks only the item named.

1. **Textbook toolkit.** May a separate worker hold two textbook-method libraries
   ([note](backlog/afml-toolkit-worker.md))? And is a barrier touched by a bar's high and low,
   as ALPHA does today, or by its close only, as the libraries do?
2. **Advisory reminder hook.** A fifth Claude Code hook now tells an AI which documents describe a
   file it edited. It cannot block anything. Keep it (pull request 203 asked)?
3. **Research protocols.** The fourteen old research protocols and their two tool-server tools
   survive the staged lane. Delete them with the tool-server cut?
4. **Old material.** Keep or drop: unfinished local work copied off the Mac, an orphaned earlier
   trading project, the old local folders on the Dell ([health plan](health-plan.md)).
5. **Cloud documents.** Hand over the project documents kept in the cloud workspace so they can
   be imported as reference.

[answers]: ../reference/project/owner-decisions-3.md#2026-11-15-five-scope-answers
[delegate]: ../reference/project/owner-decisions.md#2026-11-14-agents-merge-and-decide-routine-matters
[files]: ../reference/project/owner-decisions.md#2026-11-14-what-the-file-system-is-for
[free]: ../reference/project/owner-decisions-2.md#2026-11-14-free-real-data-on-the-dell-now
[grade]: ../reference/project/owner-decisions-3.md#2026-11-15-what-production-grade-means
[health]: ../reference/project/owner-decisions-2.md#2026-11-14-a-weekly-automatic-health-check
[live]: ../reference/project/owner-decisions.md#2026-11-14-live-trading-is-deferred
[mac]: ../reference/project/owner-decisions.md#2026-11-14-dell-now-mac-later
[mess]: ../reference/project/owner-decisions.md#2026-11-14-steady-progress-never-a-mess
[no-hft]: ../reference/project/owner-decisions-2.md#2026-11-14-never-high-frequency-trading
[partner]: ../reference/project/owner-decisions-3.md#2026-11-15-the-ai-must-be-a-research-partner-not-an-instruction-follower
[precise]: ../reference/project/owner-decisions.md#2026-11-14-precision-and-live-capital
[quantpad]: ../reference/project/owner-decisions.md#2026-11-14-quantpad-no-longer-used
[slim]: ../reference/project/owner-decisions-3.md#2026-11-15-always-slimmer
[spine]: ../reference/project/owner-decisions-3.md#2026-11-15-build-the-thin-spine-clean-then-switch-over
[status]: ../../STATUS.md
[struct]: ../reference/project/owner-decisions-2.md#2026-11-14-approvals-follow-code-structure-not-exact-bytes
[style]: ../reference/project/owner-decisions-2.md#2026-11-14-the-interface-shows-charts-with-text-in-a-quant-style-and-is-finished-later
[thin]: ../reference/project/owner-decisions-2.md#2026-11-14-thin-alpha-dramatically-rd-agent-and-qlib-are-the-proven-core
[ui]: ../reference/project/owner-decisions-2.md#2026-11-14-keep-the-user-interface
