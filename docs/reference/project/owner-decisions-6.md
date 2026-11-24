---
owner: project layer
sources:
  - docs/reference/project/owner-decisions-5.md
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
  [the build team](components/delivery-and-agent-tooling.md).

### 2026-11-19 All features work together as one system; four approvals

- **Said:** "Don't forget the whole picture. … everything needs to work together and be unified"; then
  "Yes I approve", and selected all four listed items.
- **Decided:** (1) The ten-step plan to join the parts is the work order: each step connects one more
  feature to the shared store, the one ledger, RD-Agent, the toolbox or the Workstation. Progress is
  reported against all capabilities in `uv run python scripts/status.py`, not one part. (2) Rule tests and
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

### 2026-11-22 No Touch ID for the final check; Claude runs it on request

- **Said:** "Get rid of Touch ID, it's annoying and makes things difficult and turns into a blocker."
  Through the question prompt, for the final check on held-back data: "No confirmation step"; for all
  other uses of Touch ID: "Remove it everywhere". Also: build the system robust and in the simplest
  usable form, with no extra defence layers.
- **Decided:** the final check on the [reserved period](reserved-period.md#the-owners-confirmation)
  needs no Touch ID and no confirmation step. Claude runs `alpha confirm run` when the owner asks in
  chat, and shows the plan first. The ten slots, one look per idea and per rule family on one asset,
  the frozen test, the receipt before the read and the stored result stay. Touch ID for the other
  owner actions is removed in a separate, later change.
- **Context:** the first build asked for a Touch ID touch on a local web page within 60 seconds, and
  signed and hash-chained each slot. The owner found the step a blocker.
- **Governs:** [reserved period](reserved-period.md); the
  [card](../../../research/tools/reserved-confirmation.md);
  [owner authority](../invariants/research-integrity.md#owner-authority).

### 2026-11-19 Redirect: front door, three golden paths, nightly real run, wider universe, idea card

- **Said:** "Yes I approve the re direction", after a review of the project against the researched creators' way of building and testing strategies.
- **Decided:** stop adding checks and features. Order of work: (1) one front door, where an idea is stated in plain words and the system runs it
  and shows it; (2) three golden paths: the owner's own rule, the owner's own chart setup, an RD-Agent idea; (3) all three run every night on real
  data (`alpha nightly`) as the alarm, and the universe widens only after two full runs in a row with no blocking defect; (4) a real universe
  with delisted names; (5) the idea card as the form in which ideas are proposed. The card is an addition to RD-Agent, never a cut.
- **Context:** the review found a strict judge with thin ideas and thin data, many capabilities only partly working, and no front door.
- **Governs:** [project overview](overview.md); the [nightly run card](../../../research/tools/nightly-run.md); [RD-Agent](components/rd-agent.md).

### 2026-11-19 Forward test: follow a tested idea on paper

- **Said:** exact words not recorded; the owner approved a forward test (paper, live data) among five items after a review of where more edge lies.
- **Decided:** a tested idea can be followed forward on paper: `alpha follow` freezes the idea, then records each new session. There is no
  broker paper trading and no order. A follow is not a test, and its records never become research evidence.
- **Context:** a test on past data cannot show how an idea behaves on new bars.
- **Governs:** [follow card](../../../research/tools/follow.md); [paper and live](components/paper-and-live.md).

### 2026-11-23 Remove the old research-case machinery, export first

- **Said:** exact words not recorded; the owner approved "export then delete" for the old research-case machinery.
- **Decided:** research cases, projects, evidence, the control-store tables that hold them, `alpha research`, `alpha suite` and the native case
  lane are deleted in twelve ordered steps, after a private export of the stored data. Three cards that only run inside cases are retired:
  read a native job result, the daily rule study, and Qlib in research cases. The link from a paper claim to an experiment is dropped; the
  `alpha library` shelf stays. A step that edits a protected file still needs the owner's yes for that file. The replacing path is
  `alpha test`, ideas, Setup Lab, `alpha follow` and `alpha confirm`.
- **Context:** the new pipeline replaced the case lane, and the owner wants a thin system.
- **Governs:** [research cases page](components/research-cases-and-approval.md); [command line research](../invariants/cli-research.md);
  [reserved period](reserved-period.md).

### 2026-11-24 The build team replaces the Software Team and the delivery pipeline

- **Said:** "We had in this project at one point, I think it was called the software team, that was meant to be the team we're trying to build now.
  Can we ensure there's no confusion, that the old software team that we built is removed, and it's noted everywhere that it's replaced by the team
  we're building now."
- **Decided:** the Software Team (October 2026) and the five-stage delivery pipeline are deleted: the `workflow/` folder, the stage slash commands,
  the Codex hand-off tool and the model-routing pages. The build team (a separate private repository, `alpha-factory`) replaces them.
  One page in the product says how ALPHA is built.
- **Context:** a third of merged changes were repairs, `main` was red six times in one day, and a builder inverted a research-integrity sentence
  that review passed.
- **Governs:** [the build team](components/delivery-and-agent-tooling.md);
  [ADR-0056](../../adr/0056-the-build-team-replaces-the-delivery-pipeline.md).
