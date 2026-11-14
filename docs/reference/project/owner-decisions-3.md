---
owner: project layer
sources:
  - docs/reference/project/owner-decisions.md
verified: 3eb3f1eb
---

# Owner decisions log, volume 3

Continues the [owner decisions log](owner-decisions.md) and [volume 2](owner-decisions-2.md);
the rules for entries are in the first. New entries are appended at the end of this file.

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
