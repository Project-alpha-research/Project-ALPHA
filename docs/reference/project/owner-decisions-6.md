---
owner: project layer
sources:
  - docs/reference/project/owner-decisions-5.md
verified: d3dd64079e042b98
---

# Owner decisions log, volume 6

Continues the [owner decisions log](owner-decisions.md) and volumes [2](owner-decisions-2.md),
[3](owner-decisions-3.md), [4](owner-decisions-4.md) and [5](owner-decisions-5.md); the rules for
entries are in the first. New entries are appended at the end of this file.

## Entries

### 2026-11-19 Never reduce RD-Agent's capability to save tokens or cost

- **Said:** exact words not recorded; relayed by the orchestrating AI agent, not verbatim. Never reduce
  RD-Agent's capability to save tokens or cost.
- **Decided:** the research loop (prompts, reflections, feedback, memory, history) keeps its full context.
  Token cuts apply to development overhead only. A change that removes information from the research
  loop needs the owner's explicit yes.
- **Context:** a discussion change had withheld RD-Agent's own written feedback from later prompts after
  a round with a dropped idea. The owner had it restored.
- **Governs:** `workers/rdagent`; the [RD-Agent component page](components/rd-agent.md);
  [model routing](../model-routing.md).

### 2026-11-19 All features work together as one system; four approvals

- **Said:** "Don't forget the whole picture. … everything needs to work together and be unified"; then
  "Yes I approve", and selected all four listed items.
- **Decided:** (1) The ten-step plan to join the parts is the work order: each step connects one more
  feature to the shared store, the one ledger, RD-Agent, the toolbox or the Workstation. Progress is
  reported against all capabilities in [STATUS.md](../../../STATUS.md), not one part. (2) Rule tests and
  setups also hold back data from the [reserved date](reserved-period.md) on; later data is used only
  when the owner chooses to confirm an idea. (3) RD-Agent may use chart setups, patterns and lookalike
  as inputs and may work on single assets, not only coin rankings. (4) Protected edits approved for the
  file-system work: `CLAUDE.md`, `AGENTS.md`, one rule file, `scripts/fs.py` search and freshness, and
  the hand-off script's brief template. (5) The file-system test uses the grader's pass mark: no wrong
  fact; every critical fact; core answers right on 9 of 10 by majority; a reading limit.
- **Context:** two days of work had gone almost only to RD-Agent's discussion, the toolbox and the file
  system. A map of the code showed no feature joined on all eight connection tests.
- **Governs:** [project overview](overview.md); [RD-Agent](components/rd-agent.md);
  [reserved period](reserved-period.md); [file-system measurement](file-system-measurement.md).
