---
owner: project layer
sources:
  - docs/reference/project/owner-decisions.md
verified: 4c59d794bcc9c4ff
---

# Owner decisions log, volume 3

Continues the [owner decisions log](owner-decisions.md) and [volume 2](owner-decisions-2.md);
the rules for entries are in the first. This volume is full: new entries go in [volume 4](owner-decisions-4.md).

## Entries

### 2026-11-15 What production grade means

- **Said:** "Production grade is having all capability's and a robust system/trading pipe line
  to reserash, build trading models, collect data, find edges in markets. Understand
  everything. Have all over fit test and any other capabilities available. All structured and
  useable so I can just promot an ai and everything works well. There's a systsem and
  structure. The ui is so I can see what is happening and use that to understand and oriccced
  foward. All communication with the ai can be via Claude or ChatGPT in app or terminal. Thomas
  skinner has a product called quant pad. Serash it online. I expect my system to work similar
  fi that. Mine is just much more agentic and autonmussm and has much more features."
- **Context:** answers an agent's proposal of a 34-item checklist. The owner prompts an AI, the
  AI drives the pipeline, and the interface is for seeing and understanding, not for chatting.
- **Governs:** the whole project; the [overview](overview.md).

### 2026-11-15 No daily-only rule; fewer strict rules

- **Said:** "There's no daily data only rule. I can test for anything and it propise any trading
  idea and rub it though the pipe line. The rules need to be less strict". And: "daily only
  data makes no sense. Stop making strict rules."
- **Context:** any idea at any bar timeframe goes through the pipeline. The earlier rule against
  high-frequency trading still stands. Prefer defaults, labels and warnings to refusals.
- **Governs:** the [data layer](components/data-layer.md); the whole project.

### 2026-11-15 Always slimmer

- **Said:** "Make slimed always try refactor and thin out Bloat and mess".
- **Context:** answers whether to restore the removed agent benchmark tool or replace it later
  with something slimmer: replace it with something slimmer.
- **Governs:** [delivery and agent tooling](components/delivery-and-agent-tooling.md).

### 2026-11-15 The swing-trading research is inspiration, not a rulebook

- **Said:** "Showing you all the swing trading ideas and reserash are ti help you think if
  features and actions and structure we can build to make using the product steer in the right
  direction whej using it".
- **Context:** the research the owner supplied shapes features, actions and structure. It is
  not a list of studies to run or rules to enforce.
- **Governs:** the whole project; the [overview](overview.md).

### 2026-11-15 The AI must be a research partner, not an instruction follower

- **Said:** "the ai also needs to know what to suggest. How to interpret data along the way,
  suggest tests to run, suggest data to look at." And: "It needs to be a partner in the process
  not just follow word for word instructions." And: "Think and plan what we can do so in any
  and all situations the ai is smart and understands and always learns and evolves".
- **Context:** the owner gave two examples and said they are only examples: a sharp drawdown
  should prompt a check of the one asset against the whole market and the macro data of that
  time; an edge that appears only in some periods should prompt regime detection. The project
  must teach a method and supply diagnostics, tools, context data and memory, not a script.
- **Governs:** the whole project; [AI assistants](components/ai-assistants.md).

### 2026-11-15 Adopt everything RD-Agent has, memory first

- **Said:** "Yes adopt and utilise everything rd agents has especially memory of the past".
- **Context:** answers an agent's question whether to use all of RD-Agent's own abilities
  instead of rebuilding them in ALPHA. RD-Agent stays an engine the AI partner calls.
- **Governs:** [RD-Agent](components/rd-agent.md).

### 2026-11-15 Build the thin spine clean, then switch over

- **Said:** "Clean spine."
- **Context:** answers an agent's question: keep carving the old code down piece by piece, or
  write the small new core fresh in this repository, point the screens at it, and delete the
  old lanes as each is replaced. The owner chose the second. The owner also agreed to set up
  private remote access to the Dell so the screens can be opened from a phone.
- **Governs:** the whole project; the [overview](overview.md#the-target-shape).

### 2026-11-15 The file system is always kept up to date

- **Said:** "Ensure file systsem is always being updated and accounted for".
- **Context:** said while approving the clean spine. Every change of direction, new part and
  removed part is written into the project layer in the same piece of work, not afterwards.
- **Governs:** [delivery and agent tooling](components/delivery-and-agent-tooling.md).

### 2026-11-15 Nothing planned is lost; the end goal

- **Said:** "Ensure everything we discussed and planned is included in production ready and w
  ending loose any features. The end goal is to have the most advanced and capible pipe line for
  navigating financial markets with ai. We need every capability that matches what would help
  retail traders find edge".
- **Context:** led to the [production-ready checklist](../../roadmap/production-scope.md), the
  single list of what "production ready" includes. Nothing is removed unless it is replaced,
  rebuilt slimmer, or covered by an entry in this log.
- **Governs:** the whole project.

### 2026-11-15 Five scope answers

- **Said:** "1. Yes later with free sources first 2. Tell me what you need and I will get it
  3. Yes 4. Yes optimal for the pipe like if I want ti build strgey for prop form soeifucky or
  see how one I devolp would perform on prop firm 5. Yes".
- **Context:** answers five questions from the checklist. (1) Paid or account-only data
  (options, flows, news, fundamentals) comes after production ready; free sources first.
  (2) The owner will create the free macro-data key when told what is needed. (3) The in-product
  assistant panel is removed once the investigation trail screen exists. (4) The prop-firm check
  stays as an optional pipeline tool, for building a strategy for a prop firm or seeing how one
  would perform there. (5) A "how this was computed" view per finding is enough; no whole-code map.
- **Governs:** the [data layer](components/data-layer.md), [AI assistants](components/ai-assistants.md),
  [validation and evidence](components/validation-and-evidence.md), the [Workstation](components/web-workstation.md).

### 2026-11-15 Glue in more proven open-source projects

- **Said:** "I want ti add more robust repos that are built well and not vibe coded like mine and
  have the glue like we do with qlib and rd agents it seems to work well." And: "Also should we
  use ducbBB for data handling".
- **Context:** the owner sent three examples from a social-media post (a reinforcement-learning
  trading library, a machine-learning-for-trading course, a portfolio report library) and asked
  for each to be judged, and for other projects worth gluing in. A popular project is not
  automatically adopted: each is judged on fit, upkeep, licence and what hand-written code it
  lets ALPHA delete.
- **Governs:** the whole project; the [overview](overview.md#the-target-shape).

### 2026-11-15 RD-Agent's own run viewer is installed

- **Said:** chose "Install the viewer" when asked whether to add RD-Agent's step-by-step run
  viewer as a separate pinned install or to skip it (a selection from offered options).
- **Context:** it runs in its own install, reachable only from the owner's devices.
- **Governs:** [RD-Agent](components/rd-agent.md).

### 2026-11-15 Documents can never be stale: enforced by the system, not by an AI's memory

- **Said:** "if the file system is working, we should not have any stale documents"; "take out
  the AI parts where possible"; "we shouldn't ever really have stale files. That's the point of
  the file system."
- **Context:** until now a stale document was only listed, and keeping one current relied on an
  AI remembering. Now each document records a fingerprint of the files it describes. When an AI
  edits a file it is told at once which documents describe it; the check and the pull request
  fail while any document's fingerprint is out of date; one command re-stamps a document after
  it has been re-read. A machine can prove a document is out of date and refuse the work; an AI
  still has to re-read and correct it. The research paper has no staleness rule: this is ours.
- **Governs:** [delivery and agent tooling](components/delivery-and-agent-tooling.md); the rule
  is in [documentation invariants](../invariants/documentation.md#front-matter).

### 2026-11-15 More of the suggested outside projects approved

- **Said:** "I approve adding and using more of your suggestions for the repos" (as quoted in
  pull request 201, which found it missing from this log on 2026-11-16).
- **Context:** this is the approval behind the "Approved, not yet added" rows of the register.
  Each project still arrives in its own pull request with its adapter and tests, under the glue
  rules; approval is not adoption.
- **Governs:** [outside projects register](outside-projects.md).

### 2026-11-15 Test ideas are system tests until ALPHA is production grade

- **Said:** exact words not recorded in this log; noted by the orchestrating session that day.
- **Context:** until ALPHA is production grade, every research idea, loop and strategy run is an
  end-to-end test of the system, not research. Ideas are chosen to exercise as many parts as
  possible (data, horizons, asset kinds, model routes, judge stages, paper path, screens). A run
  is reported first by what worked, broke, was slow, confusing or missing, and only briefly by
  what the idea showed; its outcome is never presented as a market finding, and no effort goes
  into rescuing an idea. The integrity machinery must still work, because it is being tested.
  Defects and friction from each run are kept in a running list.
- **Governs:** the [research route](../../../research/CONTEXT.md) and every report to the owner.

### 2026-11-15 The orchestrating session delegates; every agent names its model

- **Said:** exact words not recorded in this log; reinforced on 2026-11-16 (use Codex heavily).
- **Context:** to protect the owner's usage limits, the session the owner talks to plans, briefs,
  reviews hand-backs and lands pull requests; it does not run as a sub-agent. Every delegated
  agent states its model: a heavier one for judgement, a lighter one for mechanical work. Any
  build that can be written as a brief goes to Codex through the hand-off tool.
- **Governs:** [model routing](../model-routing.md).

### 2026-11-16 Licences are never a criterion for outside projects

- **Said:** "this project is non commercial and private so licensing and things DO NOT MATTER.
  never make a decision based off that"
- **Context:** until now an outside library, model or data source could be refused, delayed or
  marked down for its licence (for example scikit-survival, pypbo, Arize Phoenix and TimesFM's
  newest weights). From now on licence is never a reason, a risk, a tie-breaker or a footnote.
  What still decides: fit for a retail swing trader, upkeep, weight, and conflict with ALPHA's
  pinned versions. Those earlier verdicts were judged again on merit. The earlier entry above
  that lists licence among the things a project is judged on is superseded by this one.
- **Governs:** [outside projects register](outside-projects.md);
  [ADR-0052](../../adr/0052-licence-is-not-a-criterion.md).
