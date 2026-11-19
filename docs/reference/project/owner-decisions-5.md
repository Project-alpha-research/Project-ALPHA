---
owner: project layer
sources:
  - docs/reference/project/owner-decisions-4.md
verified: 9def06fde73f407c
---

# Owner decisions log, volume 5

Continues the [owner decisions log](owner-decisions.md), [volume 2](owner-decisions-2.md),
[volume 3](owner-decisions-3.md) and [volume 4](owner-decisions-4.md); the rules for entries are in
the first. This volume is full: new entries go in [volume 6](owner-decisions-6.md). Every entry below was said on
2026-11-18 and written down the same day; several repeat or extend a point in volume 4 so that the
part that owns it can link to one clear entry.

## Entries

### 2026-11-18 Stand-in user while ideas are throwaway tests

- **Said:** exact words not recorded; paraphrased by the orchestrating AI agent, not verbatim. The
  owner is busy, and while the ideas are only system tests, an AI may play the user.
- **Decided:** while RD-Agent pauses for a person, Claude or a helper agent may read its proposals
  as a trader using the software would, accept, redirect or suggest another idea. Every such answer
  is labelled "stand-in user, not the owner". It is never used for a real approval: only the owner approves reserved-data use,
  promotion, paper or live trading, guard or security changes, or deleting a feature. `apps/alpha-cli/src/alpha_cli/owner_auth.py`
  and the `pre-owner-action-guard` hook enforce it.
- **Why:** the owner cannot answer every pause, and the test phase needs the discussion flow
  exercised.
- **In practice:** each stand-in exchange is judged as a test of the collaboration flow, and the
  report says what it was like to use.
- **Governs:** [RD-Agent](components/rd-agent.md); [research cases and approval](components/research-cases-and-approval.md).
  The rule that only the owner approves: [owner authority](../invariants/research-integrity.md#owner-authority).
- **Status (2026-11-18):** the pause ("propose and discuss") mode is built on the command line only (PR #281); the Workstation screen for it is not built.

### 2026-11-18 Kronos, the four Monte Carlos, lookalike and pattern tools are RD-Agent's toolbox

- **Said:** exact words not recorded; paraphrased by the orchestrating AI agent. While approving
  deletions the owner said not to get rid of pieces of the project, naming Kronos (it "should be
  built into" ALPHA), the four Monte Carlo methods, the downloaded repositories for finding "has
  this happened before" (lookalike search) and the chart-pattern and trend-line code. They are
  "resources and tools" that RD-Agent can use. The owner also said not to lose sight of features
  that were meant to exist.
- **Why:** a slimming audit had listed the Kronos screen as a removal candidate and the owner feared
  real features would be cut.
- **Decided:** these are features to wire in, never slimming targets. A tool that is built but not
  yet reachable from RD-Agent or a screen is owed wiring, not deletion. The end state is one
  catalogue of tools that both the owner's prompts and RD-Agent can call.
- **In practice:** before removing anything feature-shaped, check it against this entry and the
  capability list. The neurotrader888 code is a side interest: simple strategy and indicator code to
  learn from, test and modify, not a priority.
- **Governs:** [toolbox](components/toolbox.md); [Monte Carlo](components/monte-carlo.md);
  [forecasting](components/forecasting.md); [strategies and signals](components/strategies-and-signals.md).

### 2026-11-18 Keep ALPHA slim continuously

- **Said:** exact words not recorded; paraphrased by the orchestrating AI agent. Keep refactoring,
  optimising and simplifying as the project grows, so there is no huge line count, inefficiency,
  slop or useless code: "slim, refactored, optimized and correct".
- **Why:** an alignment sweep on 2026-11-18 found the tracked Python had grown about 16% since the
  2026-11-14 decision to thin the project, with three backtest engines, demo screens and an old
  research-case lane still present.
- **Decided:** every change names what it replaces and deletes that in the same pull request; extend
  an existing module rather than add a parallel one; run a read-only slimming audit regularly and
  land deletion-only pull requests from it; report the line-count trend to the owner.
- **In practice:** the audit rhythm (about every five feature pull requests, and in the weekly health
  check) is the orchestrator's default. Deleting a whole feature, or remote branches, still needs the
  owner's sign-off on the list, and the previous entry protects the tools.
- **Governs:** [delivery and agent tooling](components/delivery-and-agent-tooling.md);
  [overview](overview.md#principles).

### 2026-11-18 The Workstation must not be all black; UI design waits

- **Said:** "I don't like ui being black. Some charts can stay black but not the whole ui." Also that
  some parts, such as the RD-Agent logs, were very difficult to read and understand. Later the same
  day, after seeing a light theme and two layout sketches: "None of those are really the design I
  want. Maybe let's just focus on getting everything built, and we'll come back to the UI a bit
  later." The wording is the owner's as recorded by the orchestrating AI agent, not checked
  verbatim.
- **Decided:** the screen chrome is light by default (a Light, Dim or Dark switch exists); individual
  charts may be dark. Readability beats density: larger type and plain-English story views, with the
  technical detail behind an expander. UI design is deferred again: no restructure of the Workstation
  and no unprompted design proposals. Only the RD-Agent view is reshaped, to the journey layout in the
  next entry. When UI work resumes, ask the owner for reference screenshots rather than guess.
- **Left to the owner:** when to resume Workstation design (open item N5 in the
  [triage sheet](../../roadmap/triage-2026-11.md)).
- **Governs:** [Workstation](components/web-workstation.md); the 2026-11-14 entry
  [the interface shows charts with text](owner-decisions-2.md#2026-11-14-the-interface-shows-charts-with-text-in-a-quant-style-and-is-finished-later),
  which this entry changes: the quant style is now light, not all dark.

### 2026-11-18 The idea-journey layout is approved

- **Said:** "This is much better good work." The owner had asked for the RD-Agent view to look like
  the one-idea-at-a-time prototype of 2026-11-14, with the long text kept in an expandable section.
- **Decided:** the layout is: numbered steps; for each step who acted (the AI or an ALPHA rule); one
  plain paragraph; at most three headline numbers; one annotated chart; the locked period marked on
  every date axis. The full original text stays behind an expander. The same style is to be reused for
  other result views.
- **In practice:** a text-and-table story view of RD-Agent runs had been judged unreadable; the
  journey sheet replaces it. Reuse means new result views start from this layout, not a new one.
- **Governs:** [RD-Agent](components/rd-agent.md); [Workstation](components/web-workstation.md);
  [research loop screen](../../roadmap/backlog/research-loop-screen.md).

### 2026-11-18 The toolbox is an open catalogue meant to grow to hundreds of tests

- **Said:** "don't limit it [to] the small examples. We need all possible test and system
  availability like permutation, parameter sensitivity, etc. There's hundreds of these tests. If not
  1000's." The wording is as recorded by the orchestrating AI agent.
- **Decided:** the toolbox is one registry with a uniform way to describe, find and run a test, so
  adding a test is one small module plus one catalogue entry. The owner's AI assistant and RD-Agent
  choose from the same catalogue, and every test run on a result is recorded, because running many
  tests and reporting the favourable ones is itself a form of overfitting.
- **In practice:** a catalogue of 480 candidate tests was compiled: ALPHA has 149 of them, has part of
  103 and lacks 228. It is the backlog. Each test needs an answer known in advance (a reference
  value or a planted effect) before it goes in.
- **Governs:** [toolbox](components/toolbox.md); [validation and evidence](components/validation-and-evidence.md).

### 2026-11-18 RD-Agent may choose tests but not write them (recommendation, not yet confirmed)

- **Said:** exact words not recorded. This is the orchestrator's recommendation given to the owner on
  2026-11-18. The owner has not yet confirmed or rejected it.
- **Recommended:** RD-Agent proposes ideas and may pick which tests to run from the catalogue, but
  does not write its own statistical tests; ALPHA runs trusted versions of them. The reason is to
  avoid marking its own homework and to keep results comparable between ideas.
- **Left to the owner:** confirm, change or reject.
- 2026-11-19 status: ALPHA runs a fixed set after the verdict. Choosing tests in the proposal is still open.
- **Governs:** [toolbox](components/toolbox.md); [RD-Agent](components/rd-agent.md).

### 2026-11-18 The agent is a collaborator, never a black box

- **Said:** "We can't have this become a black box. There is no set rules." The ideas being tested
  now are random ideas to see whether the system works; ALPHA must not be built around one strategy,
  and there may be hundreds. Later the same day: the agent stays autonomous and suggests ideas, but
  the user is in the loop to keep it on track, may add their own ideas and can see what the agent
  suggests. The owner does not believe profitable strategies come straight out of AI or from copying
  research papers: papers are raw material to build on. Wording as recorded by the orchestrating AI
  agent.
- **Decided:** agent flows are propose, discuss, decide with the user in the loop; capabilities are
  general (any rule, setup or data input); every step and reason is shown on screen; labels and
  explanations are preferred to silent refusals. Until the system works properly the owner will not
  use it for real strategy development.
- **Governs:** [overview](overview.md#what-alpha-is-for);
  [volume 4 entry on the purpose of ALPHA](owner-decisions-4.md#2026-11-18-what-the-owner-said-about-the-purpose-of-alpha);
  [RD-Agent](components/rd-agent.md).

### 2026-11-18 One-shot confirmation of shortlisted factors on reserved data: approved, not built

- **Said:** "Okay", to the orchestrator's proposal, as recorded by the orchestrating AI agent.
- **Decided:** shortlisted factors may be confirmed once each on the reserved data: ten slots for the
  life of the reserved window, each slot needing the owner's own yes.
- **In practice:** not built yet, and queued behind the screens. Nothing may use a slot before it is
  built, and the stand-in user (first entry) can never give the yes. Details are in the
  [volume 4 entry](owner-decisions-4.md#2026-11-18-owner-decisions-on-confirmation-the-build-sandbox-and-rd-agent-subject-matter).
- **Governs:** [RD-Agent](components/rd-agent.md).

### 2026-11-18 Codex builds with the 6.2 models; Claude orchestrates and reviews

- **Said:** exact words not recorded; paraphrased by the orchestrating AI agent. The owner named the
  new Codex 6.2 models and asked for Codex to be used more, to save Claude usage.
- **Decided:** Codex builds with the 6.2 models; Claude plans, orchestrates and reviews.
- **Governs:** [model routing](../model-routing.md);
  [delivery and agent tooling](components/delivery-and-agent-tooling.md).

### 2026-11-18 Request: one data health report

- **Said:** exact words not recorded; paraphrased by the orchestrating AI agent. The owner asked for
  one report on the health of the stored data covering price adjustments, timestamps, gaps and
  survivorship.
- **Decided:** queued, not built. It is listed in [ideas and things considered](ideas-and-considered.md). (Status, added 2026-11-19, superseded by the next
  status lines: step 1 only was built, `alpha data health` from PR #278; attaching the verdict to runs was not built then.)
- **Governs:** [data layer](components/data-layer.md).
- **Status (2026-11-18):** step 1 is built (PR #278): `alpha data health` and its saved report. Attaching the verdict to runs
  is not built. The decision above is left as recorded.
- **Status (2026-11-19):** rule tests and setup runs now carry the verdict (PR #286). RD-Agent panels remain queued.

### 2026-11-18 Rule: a directional statement lands in this log in the same change

- **Said:** exact words not recorded; the owner asked that the file system carry plans, reasons,
  things considered and ideas, and be kept updated ([volume 4](owner-decisions-4.md#2026-11-18-what-the-owner-said-about-the-purpose-of-alpha)).
  This working rule is the orchestrator's.
- **Decided:** when the owner says something directional, a decision entry goes into the pull request
  that does the work it changes, or into a documentation pull request the same day. The entry carries
  the date, the decision, the reason and what it changes in practice. An idea considered but not
  decided goes into [ideas and things considered](ideas-and-considered.md).
- **Governs:** [docs workspace](../../CONTEXT.md); [delivery and agent tooling](components/delivery-and-agent-tooling.md).

### 2026-11-18 Text the owner reads follows Simplified Technical English

- **Said:** the owner shared a tip to write "80% of the way to ASD-STE100", described the problem as
  text fatigue from long answers, asked "should we add this to our project?", and approved it.
- **Decided:** replies, reports, screen labels and pull-request summaries put the answer first, use
  short sentences with one idea in each, and keep one name for one thing. The style does not shorten
  an answer by itself: write less as well.
- **Governs:** `CLAUDE.md` (Check and land); the report-to-owner skill; [AI assistants](components/ai-assistants.md).

### 2026-11-19 Claude agents build until the Codex subscription returns; the file system comes first

- **Said:** exact words not recorded; paraphrased by the orchestrating AI agent. The owner said the Codex
  subscription has expired, and asked for the file system to match the research paper's spec first, to cut reading.
- **Decided:** until the owner says otherwise, Claude agents build (Sonnet builds, Opus reviews honesty and statistics) or the orchestrator does.
- **Governs:** [model routing](../model-routing.md); [workflow stages](../../../workflow/CONTEXT.md); [file system](../../CONTEXT.md).
